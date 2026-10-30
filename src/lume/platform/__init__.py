"""Seleção do backend e leitura de preferências do sistema."""

from __future__ import annotations

import subprocess
import sys

from lume.platform.base import DisplayBackend


def create_backend(demo: bool = False) -> DisplayBackend:
    if demo:
        from lume.platform.mock import MockBackend

        return MockBackend()
    if sys.platform == "win32":
        from lume.platform.windows import WindowsBackend

        return WindowsBackend()
    if sys.platform == "darwin":
        from lume.platform.macos import MacBackend

        return MacBackend()
    from lume.platform.linux import LinuxBackend

    return LinuxBackend()


def _quiet(cmd: list[str]) -> str:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=2, check=False)
        return res.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def prefers_reduced_motion() -> bool:
    """Lê a preferência de “reduzir movimento” do sistema, quando existe."""
    if sys.platform == "win32":
        import ctypes

        enabled = ctypes.c_int(1)
        SPI_GETCLIENTAREAANIMATION = 0x1042
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0):
            return not enabled.value
        return False
    if sys.platform == "darwin":
        return _quiet(["defaults", "read", "com.apple.universalaccess", "reduceMotion"]) == "1"
    return _quiet(["gsettings", "get", "org.gnome.desktop.interface", "enable-animations"]) == "false"


def high_contrast_enabled() -> bool:
    """Alto contraste do Windows: nesse caso a interface usa as cores do sistema."""
    if sys.platform != "win32":
        return False
    import ctypes

    class HIGHCONTRASTW(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwFlags", ctypes.c_uint), ("lpszDefaultScheme", ctypes.c_wchar_p)]

    hc = HIGHCONTRASTW()
    hc.cbSize = ctypes.sizeof(hc)
    SPI_GETHIGHCONTRAST, HCF_HIGHCONTRASTON = 0x0042, 0x1
    if ctypes.windll.user32.SystemParametersInfoW(SPI_GETHIGHCONTRAST, hc.cbSize, ctypes.byref(hc), 0):
        return bool(hc.dwFlags & HCF_HIGHCONTRASTON)
    return False
