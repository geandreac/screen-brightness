import subprocess
import sys

import pytest

from lume.platform import linux, windows

DETECT = """Display 1
   I2C bus:          /dev/i2c-4
   DRM connector:    card1-DP-1
   Monitor:          DEL:DELL U2720Q:ABC123

Invalid display
   I2C bus:          /dev/i2c-7
   DRM connector:    card1-HDMI-A-1
"""


def test_parse_ddcutil():
    found = linux.parse_ddcutil_detect(DETECT)
    assert found == [linux.DdcDisplay(4, "card1-DP-1", "DELL U2720Q")]
    assert linux.parse_ddcutil_getvcp("VCP 10 C 50 100") == (50, 100)
    assert linux.parse_ddcutil_getvcp("garbage") is None


def test_edid_name():
    edid = bytearray(128)
    edid[54:59] = b"\x00\x00\x00\xfc\x00"
    edid[59:72] = b"DELL U2720Q\n "
    assert linux.edid_name(bytes(edid)) == "DELL U2720Q"


def _sys(tmp_path):
    drm = tmp_path / "drm"
    for name, status in (("card1-eDP-1", "connected"), ("card1-DP-1", "connected"), ("card1-HDMI-A-1", "disconnected")):
        (drm / name).mkdir(parents=True)
        (drm / name / "status").write_text(status + "\n")
    bl = tmp_path / "backlight" / "intel_backlight"
    bl.mkdir(parents=True)
    (bl / "type").write_text("raw\n")
    (bl / "max_brightness").write_text("1000\n")
    (bl / "brightness").write_text("500\n")
    return drm, tmp_path / "backlight"


def test_linux_probe_with_fake_sysfs_and_ddcutil(tmp_path, monkeypatch):
    drm, backlight = _sys(tmp_path)
    calls = []

    def runner(cmd, timeout):
        calls.append(cmd)
        out = DETECT if cmd[1] == "detect" else "VCP 10 C 30 100" if cmd[1] == "getvcp" else ""
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    b = linux.LinuxBackend(runner=runner, drm_root=drm, backlight_root=backlight, use_x11=False, use_ddcutil=True)
    caps = b.probe()
    by_id = {d.id: d for d in caps.displays}
    assert set(by_id) == {"card1-eDP-1", "card1-DP-1"}
    assert by_id["card1-eDP-1"].brightness.available and by_id["card1-eDP-1"].name == "Tela integrada"
    assert by_id["card1-DP-1"].brightness.method == "DDC/CI"
    assert not caps.temperature.available and "Wayland" in caps.temperature.reason
    assert not caps.filters.available and caps.filters.hint
    assert b.read_brightness("card1-eDP-1") == 50
    assert b.read_brightness("card1-DP-1") == 30
    b.set_brightness("card1-DP-1", 80)
    assert calls[-1][:4] == ["ddcutil", "setvcp", "10", "80"]


def test_backlight_never_sent_zero():
    assert linux.percent_to_raw(0, 1000) == 1
    assert linux.percent_to_raw(100, 1000) == 1000


@pytest.mark.skipif(sys.platform == "win32", reason="permissões POSIX")
def test_backlight_permission_error_is_explained(tmp_path, monkeypatch):
    drm, backlight = _sys(tmp_path)
    monkeypatch.setattr(linux, "logind_command", lambda d, r: ["busctl"])

    def runner(cmd, timeout):
        return subprocess.CompletedProcess(cmd, 1, "", "Access denied")

    b = linux.LinuxBackend(runner=runner, drm_root=drm, backlight_root=backlight, use_x11=False, use_ddcutil=False)
    b.probe()
    (backlight / "intel_backlight" / "brightness").chmod(0o444)
    import os

    if os.geteuid() == 0:  # root ignora permissões de arquivo: só checa o caminho de escrita
        b.set_brightness("card1-eDP-1", 40)
        assert (backlight / "intel_backlight" / "brightness").read_text() == "400"
        return
    try:
        b.set_brightness("card1-eDP-1", 40)
    except linux.PermissionDeniedError as exc:
        assert exc.hint
    else:
        raise AssertionError("esperava PermissionDeniedError")


def test_windows_pure_helpers():
    assert windows.hardware_id(r"DISPLAY\BOE0812\4&2b1&0&UID8388688_0") == "BOE0812"
    assert windows.hardware_id(r"\\?\DISPLAY#BOE0812#4&2b1&0&UID8388688#{e6f07b5f}") == "BOE0812"
    assert windows.parse_wmi_brightness("DISPLAY\\A\\1_0|55\r\nlixo\n") == {"DISPLAY\\A\\1_0": 55}
    assert windows.ddc_percent(0, 50, 100) == 50 and windows.ddc_value(10, 110, 50) == 60
    script = windows.wmi_set_script("it's", 40)
    assert "'it''s'" in script and "Brightness=[byte]40" in script


@pytest.mark.skipif(sys.platform == "win32", reason="no Windows o backend é real")
def test_windows_backend_refuses_other_platforms():
    from lume.core.errors import UnsupportedError

    with pytest.raises(UnsupportedError):
        windows.WindowsBackend()


def test_windows_reset_colors_writes_linear_ramps_even_if_screen_is_adjusted():
    """--reset-colors não pode reaplicar a curva alterada que estava na tela."""
    from lume.core.color import linear_ramp

    backend = object.__new__(windows.WindowsBackend)  # sem tocar no Windows de verdade
    backend.originals = {r"\\.\DISPLAY1": object()}
    adjusted = tuple([round(v * 0.5) for v in linear_ramp(256)] for _ in range(3))  # tela escurecida
    written = []
    backend._write_ramps = lambda make: written.append(make(adjusted))
    backend.reset_color_to_linear()
    assert written == [tuple(linear_ramp(256) for _ in range(3))]
