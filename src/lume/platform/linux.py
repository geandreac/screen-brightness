"""Linux: X11 (XRandR) para cor, sysfs/logind para luz de fundo e ddcutil para DDC/CI.

* Luz de fundo: lida em /sys/class/backlight (legível por todos) e alterada
  pelo método ``SetBrightness`` do systemd‑logind, que não exige root para
  a sessão ativa. Se o logind não estiver disponível, tenta escrever no sysfs
  (só funciona se uma regra udev já der essa permissão).
* Monitores externos: DDC/CI via ``ddcutil`` (requer o módulo i2c-dev e acesso
  a /dev/i2c-*). Nada é instalado ou liberado automaticamente.
* Cor: curvas de gama por CRTC no X11. No Wayland o compositor controla as
  cores e não há API padrão para aplicativos comuns.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from lume.core.color import Matrix3, build_ramps, linear_ramp, sane_ramps
from lume.core.errors import BackendError, PermissionDeniedError, UnsupportedError
from lume.core.models import Capabilities, DisplayInfo, FeatureStatus
from lume.platform.base import DisplayBackend

Runner = Callable[[list[str], float], subprocess.CompletedProcess]

INTERNAL_PREFIXES = ("eDP", "LVDS", "DSI")


def default_runner(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


# ---------------------------------------------------------------- EDID / DRM

def edid_name(edid: bytes) -> str | None:
    """Extrai o nome do monitor (descritor 0xFC) de um bloco EDID."""
    if len(edid) < 128:
        return None
    for offset in (54, 72, 90, 108):
        block = edid[offset : offset + 18]
        if block[0:3] == b"\x00\x00\x00" and block[3] == 0xFC:
            name = block[5:18].split(b"\x0a")[0].decode("ascii", "replace").strip()
            return name or None
    return None


@dataclass(frozen=True)
class Connector:
    drm_name: str  # ex.: card1-DP-1
    short: str  # ex.: DP-1
    model: str | None

    @property
    def internal(self) -> bool:
        return self.short.startswith(INTERNAL_PREFIXES)


def drm_connectors(root: Path = Path("/sys/class/drm")) -> list[Connector]:
    found = []
    if not root.is_dir():
        return found
    for entry in sorted(root.iterdir()):
        match = re.fullmatch(r"card\d+-(.+)", entry.name)
        if not match:
            continue
        try:
            if (entry / "status").read_text().strip() != "connected":
                continue
        except OSError:
            continue
        try:
            model = edid_name((entry / "edid").read_bytes())
        except OSError:
            model = None
        found.append(Connector(entry.name, match.group(1), model))
    return found


# ---------------------------------------------------------------- luz de fundo

@dataclass(frozen=True)
class Backlight:
    name: str
    path: Path
    max_raw: int

    def read_percent(self) -> int:
        raw = int((self.path / "brightness").read_text().strip())
        return round(raw * 100 / self.max_raw)


def find_backlight(root: Path = Path("/sys/class/backlight")) -> Backlight | None:
    """Escolhe a interface preferida: firmware > platform > raw (como o systemd)."""
    if not root.is_dir():
        return None
    rank = {"firmware": 0, "platform": 1, "raw": 2}
    candidates = []
    for entry in root.iterdir():
        try:
            kind = (entry / "type").read_text().strip()
            max_raw = int((entry / "max_brightness").read_text().strip())
        except (OSError, ValueError):
            continue
        if max_raw > 0:
            candidates.append((rank.get(kind, 3), entry.name, Backlight(entry.name, entry, max_raw)))
    return min(candidates)[2] if candidates else None


def percent_to_raw(percent: int, max_raw: int) -> int:
    # Nunca envia 0: em vários painéis isso apaga a luz de fundo por completo.
    return max(1, round(max_raw * percent / 100))


def logind_command(device: str, raw: int) -> list[str] | None:
    if shutil.which("busctl"):
        return [
            "busctl", "call", "--system", "org.freedesktop.login1",
            "/org/freedesktop/login1/session/auto", "org.freedesktop.login1.Session",
            "SetBrightness", "ssu", "backlight", device, str(raw),
        ]
    if shutil.which("gdbus"):
        return [
            "gdbus", "call", "--system", "--dest", "org.freedesktop.login1",
            "--object-path", "/org/freedesktop/login1/session/auto",
            "--method", "org.freedesktop.login1.Session.SetBrightness",
            "backlight", device, str(raw),
        ]
    return None


# ---------------------------------------------------------------- ddcutil

@dataclass(frozen=True)
class DdcDisplay:
    bus: int
    connector: str | None  # nome DRM, ex.: card1-DP-1
    model: str | None


def parse_ddcutil_detect(text: str) -> list[DdcDisplay]:
    displays = []
    for block in re.split(r"\n(?=\S)", text.strip()):
        if not block.startswith("Display "):
            continue  # ignora “Invalid display” e avisos
        bus = re.search(r"I2C bus:\s*/dev/i2c-(\d+)", block)
        if not bus:
            continue
        connector = re.search(r"DRM[_ ]connector:\s*(\S+)", block)
        monitor = re.search(r"Monitor:\s*[^:]*:([^:]*):", block)
        model = re.search(r"Model:\s*(.+)", block)
        name = (monitor.group(1) if monitor else model.group(1) if model else "").strip() or None
        displays.append(DdcDisplay(int(bus.group(1)), connector.group(1) if connector else None, name))
    return displays


def parse_ddcutil_getvcp(text: str) -> tuple[int, int] | None:
    """Formato --brief: ``VCP 10 C <atual> <máximo>``."""
    match = re.search(r"VCP\s+10\s+C\s+(\d+)\s+(\d+)", text)
    if not match:
        return None
    current, maximum = int(match.group(1)), int(match.group(2))
    return (current, maximum) if maximum > 0 else None


def ddcutil_hint(stderr: str) -> str:
    low = stderr.lower()
    if "permission" in low or "eacces" in low:
        return "Seu usuário precisa de acesso a /dev/i2c-* (geralmente o grupo “i2c”). Veja o README."
    if "i2c" in low and ("no /dev" in low or "not loaded" in low or "module" in low):
        return "Carregue o módulo i2c-dev (sudo modprobe i2c-dev). Veja o README."
    return "Verifique se a opção DDC/CI está ligada no menu do monitor."


# ---------------------------------------------------------------- X11 / XRandR

class _ScreenResources(ctypes.Structure):
    _fields_ = [
        ("timestamp", ctypes.c_ulong),
        ("configTimestamp", ctypes.c_ulong),
        ("ncrtc", ctypes.c_int),
        ("crtcs", ctypes.POINTER(ctypes.c_ulong)),
        ("noutput", ctypes.c_int),
        ("outputs", ctypes.POINTER(ctypes.c_ulong)),
        ("nmode", ctypes.c_int),
        ("modes", ctypes.c_void_p),
    ]


class _OutputInfo(ctypes.Structure):
    _fields_ = [
        ("timestamp", ctypes.c_ulong),
        ("crtc", ctypes.c_ulong),
        ("name", ctypes.c_char_p),
        ("nameLen", ctypes.c_int),
        ("mm_width", ctypes.c_ulong),
        ("mm_height", ctypes.c_ulong),
        ("connection", ctypes.c_ushort),
        ("subpixel_order", ctypes.c_ushort),
        ("ncrtc", ctypes.c_int),
        ("crtcs", ctypes.POINTER(ctypes.c_ulong)),
        ("nclone", ctypes.c_int),
        ("clones", ctypes.POINTER(ctypes.c_ulong)),
        ("nmode", ctypes.c_int),
        ("npreferred", ctypes.c_int),
        ("modes", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _CrtcGamma(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_int),
        ("red", ctypes.POINTER(ctypes.c_ushort)),
        ("green", ctypes.POINTER(ctypes.c_ushort)),
        ("blue", ctypes.POINTER(ctypes.c_ushort)),
    ]


class X11Gamma:
    """Curvas de gama por CRTC via libXrandr (o mesmo mecanismo do redshift)."""

    def __init__(self, display_name: str | None = None):
        x11_path = ctypes.util.find_library("X11")
        xrr_path = ctypes.util.find_library("Xrandr")
        if not x11_path or not xrr_path:
            raise UnsupportedError(
                "As bibliotecas libX11/libXrandr não foram encontradas.",
                "Instale o pacote libxrandr2 (ou equivalente da sua distribuição).",
            )
        self.x = x = ctypes.CDLL(x11_path)
        self.xrr = xrr = ctypes.CDLL(xrr_path)
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XDefaultRootWindow.restype = ctypes.c_ulong
        x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        xrr.XRRGetScreenResourcesCurrent.restype = ctypes.POINTER(_ScreenResources)
        xrr.XRRGetScreenResourcesCurrent.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xrr.XRRFreeScreenResources.argtypes = [ctypes.POINTER(_ScreenResources)]
        xrr.XRRGetOutputInfo.restype = ctypes.POINTER(_OutputInfo)
        xrr.XRRGetOutputInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ScreenResources), ctypes.c_ulong]
        xrr.XRRFreeOutputInfo.argtypes = [ctypes.POINTER(_OutputInfo)]
        xrr.XRRGetCrtcGammaSize.restype = ctypes.c_int
        xrr.XRRGetCrtcGammaSize.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xrr.XRRGetCrtcGamma.restype = ctypes.POINTER(_CrtcGamma)
        xrr.XRRGetCrtcGamma.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xrr.XRRAllocGamma.restype = ctypes.POINTER(_CrtcGamma)
        xrr.XRRAllocGamma.argtypes = [ctypes.c_int]
        xrr.XRRSetCrtcGamma.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_CrtcGamma)]
        xrr.XRRFreeGamma.argtypes = [ctypes.POINTER(_CrtcGamma)]

        self.dpy = x.XOpenDisplay(display_name.encode() if display_name else None)
        if not self.dpy:
            raise UnsupportedError("Não foi possível conectar ao servidor X11.")
        self.lock = threading.Lock()
        self.outputs: list[tuple[str, int]] = []  # (nome da saída, crtc)
        self.originals: dict[int, tuple[list[int], list[int], list[int]]] = {}
        self._scan()

    def _scan(self) -> None:
        root = self.x.XDefaultRootWindow(self.dpy)
        res = self.xrr.XRRGetScreenResourcesCurrent(self.dpy, root)
        if not res:
            raise UnsupportedError("O servidor X11 não oferece a extensão RandR.")
        try:
            for i in range(res.contents.noutput):
                info = self.xrr.XRRGetOutputInfo(self.dpy, res, res.contents.outputs[i])
                if not info:
                    continue
                try:
                    out = info.contents
                    if out.connection == 0 and out.crtc:  # 0 = RR_Connected
                        self.outputs.append((out.name.decode(errors="replace"), out.crtc))
                finally:
                    self.xrr.XRRFreeOutputInfo(info)
        finally:
            self.xrr.XRRFreeScreenResources(res)
        for _, crtc in self.outputs:
            if crtc in self.originals:
                continue
            size = self.xrr.XRRGetCrtcGammaSize(self.dpy, crtc)
            if size < 2:
                continue
            gamma = self.xrr.XRRGetCrtcGamma(self.dpy, crtc)
            if not gamma:
                ramp = linear_ramp(size)
                self.originals[crtc] = (ramp, list(ramp), list(ramp))
                continue
            g = gamma.contents
            self.originals[crtc] = sane_ramps(
                [[ch[k] for k in range(g.size)] for ch in (g.red, g.green, g.blue)]
            )
            self.xrr.XRRFreeGamma(gamma)

    def _set(self, crtc: int, ramps) -> None:
        size = len(ramps[0])
        gamma = self.xrr.XRRAllocGamma(size)
        if not gamma:
            raise BackendError("Sem memória para a curva de gama.")
        try:
            g = gamma.contents
            for dest, src in zip((g.red, g.green, g.blue), ramps):
                for k, value in enumerate(src):
                    dest[k] = value
            self.xrr.XRRSetCrtcGamma(self.dpy, crtc, gamma)
        finally:
            self.xrr.XRRFreeGamma(gamma)

    def apply(self, gains) -> None:
        with self.lock:
            for crtc, base in self.originals.items():
                self._set(crtc, build_ramps(base, gains))
            self.x.XSync(self.dpy, 0)

    def restore(self) -> None:
        with self.lock:
            for crtc, base in self.originals.items():
                self._set(crtc, base)
            self.x.XSync(self.dpy, 0)

    def reset_linear(self) -> None:
        with self.lock:
            for crtc, base in self.originals.items():
                ramp = linear_ramp(len(base[0]))
                self._set(crtc, (ramp, ramp, ramp))
            self.x.XSync(self.dpy, 0)

    def close(self) -> None:
        with self.lock:
            if self.dpy:
                self.x.XCloseDisplay(self.dpy)
                self.dpy = None


def session_type() -> str:
    kind = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if kind:
        return kind
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    return "x11" if os.environ.get("DISPLAY") else "tty"


# ---------------------------------------------------------------- backend

class LinuxBackend(DisplayBackend):
    def __init__(
        self,
        *,
        runner: Runner = default_runner,
        drm_root: Path = Path("/sys/class/drm"),
        backlight_root: Path = Path("/sys/class/backlight"),
        use_x11: bool | None = None,
        use_ddcutil: bool | None = None,
    ):
        self.run = runner
        self.drm_root = drm_root
        self.backlight_root = backlight_root
        self.use_x11 = use_x11
        self.use_ddcutil = use_ddcutil
        self.gamma: X11Gamma | None = None
        self.backlight: Backlight | None = None
        self.backlight_display: str | None = None
        self.ddc: dict[str, tuple[DdcDisplay, int]] = {}  # display id -> (monitor, máximo VCP)

    # -- detecção -------------------------------------------------------
    def probe(self) -> Capabilities:
        notes: list[str] = []
        kind = session_type()
        color = self._probe_color(kind)
        connectors = drm_connectors(self.drm_root)
        self.backlight = find_backlight(self.backlight_root)
        ddc_map, ddc_problem = self._probe_ddc(connectors)

        displays: list[DisplayInfo] = []
        backlight_used = False
        for conn in connectors:
            name = "Tela integrada" if conn.internal else (conn.model or f"Monitor {conn.short}")
            if conn.internal and self.backlight and not backlight_used:
                backlight_used = True
                self.backlight_display = conn.drm_name
                status = FeatureStatus.ok(f"Luz de fundo ({self.backlight.name})")
                displays.append(DisplayInfo(conn.drm_name, name, True, status, 1, 10))
            elif conn.drm_name in ddc_map:
                status = FeatureStatus.ok("DDC/CI")
                displays.append(DisplayInfo(conn.drm_name, name, conn.internal, status, 0, 0))
            else:
                displays.append(DisplayInfo(conn.drm_name, name, conn.internal, self._no_brightness(conn, ddc_problem)))
        self.ddc = {key: value for key, value in ddc_map.items() if any(d.id == key for d in displays)}

        if not displays and self.backlight:
            self.backlight_display = "backlight"
            displays.append(
                DisplayInfo("backlight", "Tela integrada", True,
                            FeatureStatus.ok(f"Luz de fundo ({self.backlight.name})"), 1, 10)
            )
        if not displays and self.gamma:
            for out_name, _ in self.gamma.outputs:
                displays.append(DisplayInfo(f"x11:{out_name}", f"Saída {out_name}", False,
                                            self._no_brightness(None, ddc_problem)))

        if kind == "wayland":
            notes.append("Sessão Wayland: o compositor controla as cores da tela.")
        filters = FeatureStatus.missing(
            "No Linux não há API padrão para aplicar uma matriz de cor à tela inteira.",
            "Experimente os filtros na prévia deste app. No KDE Plasma 6 há a opção "
            "“Correção de daltonismo” em Acessibilidade.",
        )
        return Capabilities(
            platform_label=f"Linux ({'Wayland' if kind == 'wayland' else 'X11' if kind == 'x11' else kind})",
            displays=tuple(displays),
            temperature=color,
            soft_dim=color,
            filters=filters,
            notes=tuple(notes),
        )

    def _no_brightness(self, conn: Connector | None, ddc_problem: str) -> FeatureStatus:
        if conn is not None and conn.internal:
            return FeatureStatus.missing(
                "Nenhuma interface de luz de fundo foi encontrada em /sys/class/backlight.",
                "Use o controle de brilho do sistema ou o escurecimento por software.",
            )
        return FeatureStatus.missing(
            "O brilho deste monitor não pôde ser controlado por DDC/CI.",
            ddc_problem or "Use os botões do monitor ou o escurecimento por software.",
        )

    def _probe_color(self, kind: str) -> FeatureStatus:
        if kind == "wayland" and not self.use_x11:
            return FeatureStatus.missing(
                "No Wayland, aplicativos comuns não podem alterar a curva de cor da tela.",
                "Use a Luz Noturna do GNOME (Configurações › Telas), a Cor Noturna do KDE "
                "ou, em compositores wlroots, gammastep/wlsunset.",
            )
        if self.use_x11 is False or not os.environ.get("DISPLAY"):
            return FeatureStatus.missing("Nenhuma sessão gráfica X11 foi encontrada.")
        try:
            self.gamma = X11Gamma()
        except BackendError as exc:
            return FeatureStatus.missing(exc.message, exc.hint)
        if not self.gamma.originals:
            return FeatureStatus.missing(
                "O servidor X11 não expõe curvas de gama para as saídas conectadas.",
                "Isso é comum em máquinas virtuais e áreas de trabalho remotas.",
            )
        return FeatureStatus.ok("Curva de gama (XRandR)")

    def _probe_ddc(self, connectors: list[Connector]) -> tuple[dict[str, tuple[DdcDisplay, int]], str]:
        enabled = self.use_ddcutil if self.use_ddcutil is not None else bool(shutil.which("ddcutil"))
        if not enabled:
            return {}, "Instale o ddcutil para controlar monitores externos por DDC/CI."
        try:
            res = self.run(["ddcutil", "detect", "--terse"], 20)
        except (OSError, subprocess.TimeoutExpired):
            return {}, "O ddcutil não respondeu."
        found = parse_ddcutil_detect(res.stdout)
        if not found:
            return {}, ddcutil_hint(res.stderr)
        known = {c.drm_name for c in connectors}
        result = {}
        for monitor in found:
            key = monitor.connector if monitor.connector in known else None
            if key is None:
                continue
            try:
                vcp = self.run(["ddcutil", "getvcp", "10", "--brief", "--bus", str(monitor.bus)], 10)
            except (OSError, subprocess.TimeoutExpired):
                continue
            parsed = parse_ddcutil_getvcp(vcp.stdout)
            if parsed:
                result[key] = (monitor, parsed[1])
        return result, ""

    # -- brilho ---------------------------------------------------------
    def read_brightness(self, display_id: str) -> int | None:
        if display_id == self.backlight_display and self.backlight:
            try:
                return self.backlight.read_percent()
            except (OSError, ValueError):
                return None
        if display_id in self.ddc:
            monitor, _ = self.ddc[display_id]
            res = self.run(["ddcutil", "getvcp", "10", "--brief", "--bus", str(monitor.bus)], 10)
            parsed = parse_ddcutil_getvcp(res.stdout)
            return round(parsed[0] * 100 / parsed[1]) if parsed else None
        return None

    def set_brightness(self, display_id: str, percent: int) -> None:
        if display_id == self.backlight_display and self.backlight:
            self._set_backlight(percent)
        elif display_id in self.ddc:
            monitor, maximum = self.ddc[display_id]
            value = round(maximum * percent / 100)
            try:
                res = self.run(["ddcutil", "setvcp", "10", str(value), "--bus", str(monitor.bus)], 10)
            except subprocess.TimeoutExpired as exc:
                raise BackendError("O monitor demorou demais para responder ao DDC/CI.") from exc
            if res.returncode != 0:
                raise BackendError("O monitor recusou o novo brilho via DDC/CI.", ddcutil_hint(res.stderr))
        else:
            raise UnsupportedError("O brilho desta tela não pode ser controlado pelo programa.")

    def _set_backlight(self, percent: int) -> None:
        assert self.backlight is not None
        raw = percent_to_raw(percent, self.backlight.max_raw)
        cmd = logind_command(self.backlight.name, raw)
        if cmd:
            try:
                res = self.run(cmd, 5)
                if res.returncode == 0:
                    return
                detail = res.stderr.strip()
            except (OSError, subprocess.TimeoutExpired) as exc:
                detail = str(exc)
        else:
            detail = "busctl/gdbus não encontrados"
        try:
            (self.backlight.path / "brightness").write_text(str(raw))
        except PermissionError as exc:
            raise PermissionDeniedError(
                f"O sistema não permitiu alterar a luz de fundo ({detail}).",
                "Isso costuma acontecer fora de uma sessão local ativa. Use o controle de "
                "brilho do sistema ou o escurecimento por software.",
            ) from exc
        except OSError as exc:
            raise BackendError(f"Falha ao alterar a luz de fundo: {exc}.") from exc

    # -- cor ------------------------------------------------------------
    def set_color_gains(self, gains) -> None:
        if not self.gamma or not self.gamma.originals:
            raise UnsupportedError("Ajuste de cor indisponível nesta sessão.")
        self.gamma.apply(gains)

    def set_filter(self, matrix: Matrix3 | None) -> None:
        if matrix is not None:
            raise UnsupportedError("Filtros de tela inteira não são suportados no Linux.")

    def restore_color(self) -> None:
        if self.gamma:
            self.gamma.restore()

    def reset_color_to_linear(self) -> None:
        if not self.gamma:
            raise UnsupportedError("Nenhuma sessão X11 com curva de gama disponível.")
        self.gamma.reset_linear()

    def close(self) -> None:
        if self.gamma:
            self.gamma.close()
