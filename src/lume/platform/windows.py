"""Windows: WMI para tela integrada, DDC/CI (dxva2) para externos,
SetDeviceGammaRamp para cor e a Magnification API para filtros.

Limites importantes, todos tratados como erro explicável (nunca contornados):
* O Windows recusa curvas de gama muito distantes da identidade. Não alteramos
  o registro para ampliar esse limite.
* Com HDR ativo, ou com a Luz Noturna do Windows ligada, a curva de gama pode
  ser ignorada ou sobrescrita pelo sistema.
* O filtro de tela inteira só existe enquanto o programa está aberto.
"""

from __future__ import annotations

import ctypes
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Callable

from lume.core.color import Matrix3, build_ramps, linear_ramp, sane_ramps, to_color_effect_5x5
from lume.core.errors import BackendError, PermissionDeniedError, UnsupportedError
from lume.core.models import Capabilities, DisplayInfo, FeatureStatus
from lume.platform.base import DisplayBackend

Runner = Callable[[str, float], subprocess.CompletedProcess]

CREATE_NO_WINDOW = 0x08000000


def powershell_runner(script: str, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout, check=False,
        creationflags=CREATE_NO_WINDOW,
    )


# ---------------------------------------------------------------- lógica pura (testável)

WMI_QUERY = (
    "Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop | "
    "ForEach-Object { \"$($_.InstanceName)|$($_.CurrentBrightness)\" }"
)


def wmi_set_script(instance: str, percent: int) -> str:
    safe = instance.replace("'", "''")
    return (
        "Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop | "
        f"Where-Object InstanceName -eq '{safe}' | "
        f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness=[byte]{int(percent)}}}"
        " | Out-Null"
    )


def parse_wmi_brightness(text: str) -> dict[str, int]:
    out = {}
    for line in text.splitlines():
        if "|" not in line:
            continue
        name, _, value = line.strip().rpartition("|")
        if name and value.isdigit():
            out[name] = int(value)
    return out


def hardware_id(device_or_instance: str) -> str | None:
    """Extrai o código do monitor (ex.: ``BOE0812``) de um InstanceName WMI
    (``DISPLAY\\BOE0812\\4&...``) ou de um DeviceID (``\\\\?\\DISPLAY#BOE0812#...``)."""
    match = re.search(r"DISPLAY[\\#]([A-Za-z0-9]+)[\\#]", device_or_instance, re.IGNORECASE)
    return match.group(1).upper() if match else None


def ddc_percent(minimum: int, current: int, maximum: int) -> int:
    if maximum <= minimum:
        return 0
    return round((current - minimum) * 100 / (maximum - minimum))


def ddc_value(minimum: int, maximum: int, percent: int) -> int:
    return minimum + round((maximum - minimum) * percent / 100)


# ---------------------------------------------------------------- Win32

@dataclass
class _Monitor:
    id: str  # \\.\DISPLAY1
    name: str
    hardware_id: str | None
    physical: list  # handles DDC/CI
    ddc_range: tuple[int, int] | None = None
    wmi_instance: str | None = None


class WindowsBackend(DisplayBackend):
    def __init__(self, runner: Runner = powershell_runner):
        if sys.platform != "win32":
            raise UnsupportedError("Este backend só funciona no Windows.")
        from ctypes import wintypes as wt

        self.wt = wt
        self.run = runner
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        try:
            self.dxva2 = ctypes.WinDLL("dxva2", use_last_error=True)
        except OSError:
            self.dxva2 = None
        self.monitors: dict[str, _Monitor] = {}
        self.originals: dict[str, object] = {}  # id -> WORD[768]
        self.lock = threading.Lock()
        self.mag = None
        self.mag_ready = False
        self.mag_problem = ""
        self._define_types()

    def _define_types(self) -> None:
        wt = self.wt

        class RECT(ctypes.Structure):
            _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]

        class MONITORINFOEXW(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", RECT), ("rcWork", RECT),
                        ("dwFlags", wt.DWORD), ("szDevice", wt.WCHAR * 32)]

        class DISPLAY_DEVICEW(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("DeviceName", wt.WCHAR * 32), ("DeviceString", wt.WCHAR * 128),
                        ("StateFlags", wt.DWORD), ("DeviceID", wt.WCHAR * 128), ("DeviceKey", wt.WCHAR * 128)]

        class PHYSICAL_MONITOR(ctypes.Structure):
            _pack_ = 1
            _fields_ = [("hPhysicalMonitor", wt.HANDLE), ("szPhysicalMonitorDescription", wt.WCHAR * 128)]

        self.RECT, self.MONITORINFOEXW = RECT, MONITORINFOEXW
        self.DISPLAY_DEVICEW, self.PHYSICAL_MONITOR = DISPLAY_DEVICEW, PHYSICAL_MONITOR
        self.MONITORENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(RECT), wt.LPARAM)
        self.user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.c_void_p]
        self.user32.EnumDisplayDevicesW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.c_void_p, wt.DWORD]
        self.gdi32.CreateDCW.restype = wt.HDC
        self.gdi32.CreateDCW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p]
        self.gdi32.DeleteDC.argtypes = [wt.HDC]
        self.gdi32.GetDeviceGammaRamp.argtypes = [wt.HDC, ctypes.c_void_p]
        self.gdi32.SetDeviceGammaRamp.argtypes = [wt.HDC, ctypes.c_void_p]

    # -- detecção -------------------------------------------------------
    def _enum_hmonitors(self) -> list:
        handles = []

        def callback(hmon, hdc, rect, data):
            handles.append(hmon)
            return True

        self.user32.EnumDisplayMonitors(None, None, self.MONITORENUMPROC(callback), 0)
        return handles

    def _monitor_device(self, device: str) -> tuple[str, str | None]:
        dd = self.DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(dd)
        EDD_GET_DEVICE_INTERFACE_NAME = 1
        if self.user32.EnumDisplayDevicesW(device, 0, ctypes.byref(dd), EDD_GET_DEVICE_INTERFACE_NAME):
            return dd.DeviceString or "Monitor", hardware_id(dd.DeviceID)
        return "Monitor", None

    def _physical(self, hmon) -> list:
        if not self.dxva2:
            return []
        count = self.wt.DWORD()
        if not self.dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(count)) or not count.value:
            return []
        arr = (self.PHYSICAL_MONITOR * count.value)()
        if not self.dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, count.value, arr):
            return []
        return list(arr)

    def _ddc_read(self, handle) -> tuple[int, int, int] | None:
        lo, cur, hi = self.wt.DWORD(), self.wt.DWORD(), self.wt.DWORD()
        if self.dxva2.GetMonitorBrightness(handle, ctypes.byref(lo), ctypes.byref(cur), ctypes.byref(hi)):
            return lo.value, cur.value, hi.value
        return None

    def _create_dc(self, device: str):
        hdc = self.gdi32.CreateDCW(None, device, None, None)
        return hdc or self.gdi32.CreateDCW("DISPLAY", device, None, None)

    def probe(self) -> Capabilities:
        self.close_physical()
        self.monitors.clear()
        for hmon in self._enum_hmonitors():
            info = self.MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(info)
            if not self.user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                continue
            name, hwid = self._monitor_device(info.szDevice)
            mon = _Monitor(info.szDevice, name, hwid, self._physical(hmon))
            for phys in mon.physical:
                reading = self._ddc_read(phys.hPhysicalMonitor)
                if reading:
                    mon.ddc_range = (reading[0], reading[2])
                    break
            self.monitors[mon.id] = mon

        wmi = self._wmi_read()
        for instance in wmi:
            hwid = hardware_id(instance)
            candidates = [m for m in self.monitors.values() if m.ddc_range is None]
            match = next((m for m in candidates if hwid and m.hardware_id == hwid), None)
            if match is None and len(candidates) == 1:
                match = candidates[0]
            if match:
                match.wmi_instance = instance

        displays = []
        for mon in self.monitors.values():
            if mon.wmi_instance:
                status = FeatureStatus.ok("Tela integrada (WMI)")
            elif mon.ddc_range:
                status = FeatureStatus.ok("DDC/CI")
            else:
                status = FeatureStatus.missing(
                    "Este monitor não respondeu ao DDC/CI.",
                    "Ligue a opção DDC/CI no menu do monitor (nem todos oferecem, e alguns "
                    "adaptadores/docks bloqueiam). Use também o escurecimento por software.",
                )
            displays.append(DisplayInfo(mon.id, mon.name, mon.wmi_instance is not None, status))

        color = self._probe_gamma()
        filters = self._probe_magnification()
        return Capabilities(
            platform_label="Windows",
            displays=tuple(displays),
            temperature=color,
            soft_dim=color,
            filters=filters,
            notes=(
                "Com HDR ativo ou com a Luz Noturna do Windows ligada, o sistema pode "
                "ignorar ou sobrescrever a temperatura de cor deste app.",
            ),
        )

    def _wmi_read(self) -> dict[str, int]:
        try:
            res = self.run(WMI_QUERY, 15)
        except (OSError, subprocess.TimeoutExpired):
            return {}
        return parse_wmi_brightness(res.stdout) if res.returncode == 0 else {}

    def _probe_gamma(self) -> FeatureStatus:
        self.originals.clear()
        for mon in self.monitors.values():
            hdc = self._create_dc(mon.id)
            if not hdc:
                continue
            try:
                ramp = (self.wt.WORD * 768)()
                if self.gdi32.GetDeviceGammaRamp(hdc, ctypes.byref(ramp)):
                    self.originals[mon.id] = ramp
            finally:
                self.gdi32.DeleteDC(hdc)
        if not self.originals:
            return FeatureStatus.missing(
                "O driver de vídeo não permite ler a curva de gama.",
                "Isso acontece em algumas máquinas virtuais, sessões remotas e com HDR ativo.",
            )
        return FeatureStatus.ok("Curva de gama (GDI)")

    def _probe_magnification(self) -> FeatureStatus:
        try:
            self.mag = ctypes.WinDLL("Magnification", use_last_error=True)
            self.mag.MagSetFullscreenColorEffect.argtypes = [ctypes.c_void_p]
        except (OSError, AttributeError):
            return FeatureStatus.missing(
                "A Magnification API do Windows (8 ou superior) não está disponível.",
                "Use Configurações › Acessibilidade › Filtros de cor.",
            )
        return FeatureStatus.ok("Matriz de cor (Magnification API)")

    # -- brilho ---------------------------------------------------------
    def read_brightness(self, display_id: str) -> int | None:
        mon = self.monitors.get(display_id)
        if not mon:
            return None
        if mon.wmi_instance:
            return self._wmi_read().get(mon.wmi_instance)
        for phys in mon.physical:
            reading = self._ddc_read(phys.hPhysicalMonitor)
            if reading:
                return ddc_percent(*reading)
        return None

    def set_brightness(self, display_id: str, percent: int) -> None:
        mon = self.monitors.get(display_id)
        if mon is None:
            raise UnsupportedError("Tela não encontrada. Ela pode ter sido desconectada.")
        if mon.wmi_instance:
            try:
                res = self.run(wmi_set_script(mon.wmi_instance, percent), 15)
            except subprocess.TimeoutExpired as exc:
                raise BackendError("O Windows demorou demais para alterar o brilho.") from exc
            if res.returncode != 0:
                if "denied" in res.stderr.lower() or "negado" in res.stderr.lower():
                    raise PermissionDeniedError("O Windows negou acesso ao controle de brilho.")
                raise BackendError("O Windows recusou o novo brilho.", res.stderr.strip()[:200])
            return
        if mon.ddc_range:
            value = ddc_value(*mon.ddc_range, percent)
            for phys in mon.physical:
                if self.dxva2.SetMonitorBrightness(phys.hPhysicalMonitor, self.wt.DWORD(value)):
                    return
            raise BackendError("O monitor não aceitou o comando DDC/CI.",
                               "Verifique se o DDC/CI continua ligado no menu do monitor.")
        raise UnsupportedError("O brilho desta tela não pode ser controlado pelo programa.")

    # -- cor ------------------------------------------------------------
    def _write_ramps(self, make) -> None:
        failed = []
        with self.lock:
            for device, original in self.originals.items():
                base = sane_ramps([[original[c * 256 + i] for i in range(256)] for c in range(3)])
                ramps = make(base)
                buf = (self.wt.WORD * 768)(*[v for ch in ramps for v in ch])
                hdc = self._create_dc(device)
                ok = bool(hdc) and self.gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(buf))
                if hdc:
                    self.gdi32.DeleteDC(hdc)
                if not ok:
                    failed.append(device)
        if failed:
            raise BackendError(
                "O Windows recusou esta curva de cor (limite de segurança do sistema).",
                "Tente um valor menos intenso de temperatura ou de escurecimento.",
            )

    def set_color_gains(self, gains) -> None:
        if not self.originals:
            raise UnsupportedError("Ajuste de cor indisponível.")
        self._write_ramps(lambda base: build_ramps(base, gains))

    def set_filter(self, matrix: Matrix3 | None) -> None:
        if self.mag is None:
            if matrix is None:
                return
            raise UnsupportedError("Filtros de tela inteira indisponíveis.")
        with self.lock:
            if matrix is None:
                if self.mag_ready:
                    identity = (ctypes.c_float * 25)(*to_color_effect_5x5(((1, 0, 0), (0, 1, 0), (0, 0, 1))))
                    self.mag.MagSetFullscreenColorEffect(ctypes.byref(identity))
                    self.mag.MagUninitialize()
                    self.mag_ready = False
                return
            if not self.mag_ready:
                if not self.mag.MagInitialize():
                    raise BackendError(
                        "O Windows não iniciou a API de filtros de cor.",
                        "Ela não funciona com Python 32 bits em Windows 64 bits; use a versão de 64 bits.",
                    )
                self.mag_ready = True
            effect = (ctypes.c_float * 25)(*to_color_effect_5x5(matrix))
            if not self.mag.MagSetFullscreenColorEffect(ctypes.byref(effect)):
                raise BackendError(
                    "O Windows recusou o filtro de cor.",
                    "Desative os Filtros de cor do Windows, se estiverem ligados, e tente de novo.",
                )

    def restore_color(self) -> None:
        self.set_filter(None)
        if self.originals:
            self._write_ramps(lambda base: base)

    def reset_color_to_linear(self) -> None:
        """Emergência (--reset-colors): curvas neutras, sem depender do que está na tela.

        ``restore_color`` não serve aqui: as “originais” são lidas da tela no
        início, então reaplicaria uma curva que ainda estivesse alterada.
        """
        if not self.originals:
            raise UnsupportedError("Ajuste de cor indisponível.")
        self._write_ramps(lambda base: tuple(linear_ramp(len(ch)) for ch in base))

    def close_physical(self) -> None:
        if not self.dxva2:
            return
        for mon in self.monitors.values():
            if mon.physical:
                arr = (self.PHYSICAL_MONITOR * len(mon.physical))(*mon.physical)
                self.dxva2.DestroyPhysicalMonitors(len(mon.physical), arr)
                mon.physical = []

    def close(self) -> None:
        self.close_physical()
