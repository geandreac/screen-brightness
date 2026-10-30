"""macOS: curva de cor via CoreGraphics (API pública).

* Brilho de hardware: o macOS não oferece API pública e estável para isso
  (as alternativas usam frameworks privados), então o recurso é declarado
  indisponível em vez de usar APIs privadas.
* Filtros: não há API pública de matriz de cor para a tela inteira; o
  próprio sistema oferece Filtros de cor em Acessibilidade.
* O macOS restaura as cores originais quando o app fecha.
"""

from __future__ import annotations

import ctypes
import sys
import threading

from lume.core.color import Matrix3
from lume.core.errors import BackendError, UnsupportedError
from lume.core.models import Capabilities, DisplayInfo, FeatureStatus
from lume.platform.base import DisplayBackend

CG_PATH = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"


class MacBackend(DisplayBackend):
    def __init__(self):
        if sys.platform != "darwin":
            raise UnsupportedError("Este backend só funciona no macOS.")
        cg = self.cg = ctypes.CDLL(CG_PATH)
        u32, f = ctypes.c_uint32, ctypes.c_float
        cg.CGGetOnlineDisplayList.argtypes = [u32, ctypes.POINTER(u32), ctypes.POINTER(u32)]
        cg.CGDisplayIsBuiltin.argtypes = [u32]
        cg.CGDisplayGammaTableCapacity.argtypes = [u32]
        cg.CGDisplayGammaTableCapacity.restype = u32
        cg.CGGetDisplayTransferByTable.argtypes = [
            u32, u32, ctypes.POINTER(f), ctypes.POINTER(f), ctypes.POINTER(f), ctypes.POINTER(u32)
        ]
        cg.CGSetDisplayTransferByTable.argtypes = [
            u32, u32, ctypes.POINTER(f), ctypes.POINTER(f), ctypes.POINTER(f)
        ]
        self.ids: list[int] = []
        self.originals: dict[int, tuple[list[float], list[float], list[float]]] = {}
        self.lock = threading.Lock()

    def probe(self) -> Capabilities:
        u32 = ctypes.c_uint32
        ids, count = (u32 * 16)(), u32()
        if self.cg.CGGetOnlineDisplayList(16, ids, ctypes.byref(count)) != 0:
            raise BackendError("O macOS não informou a lista de telas.")
        self.ids = list(ids[: count.value])
        displays = []
        external = 0
        for did in self.ids:
            builtin = bool(self.cg.CGDisplayIsBuiltin(did))
            if not builtin:
                external += 1
            name = "Tela integrada" if builtin else f"Monitor externo {external}"
            displays.append(DisplayInfo(
                str(did), name, builtin,
                FeatureStatus.missing(
                    "O macOS não oferece uma API pública para alterar o brilho de hardware.",
                    "Use as teclas de brilho ou a Central de Controle; aqui, o escurecimento por software.",
                ),
            ))
            capacity = self.cg.CGDisplayGammaTableCapacity(did)
            if capacity < 2:
                continue
            r, g, b, n = (ctypes.c_float * capacity)(), (ctypes.c_float * capacity)(), (ctypes.c_float * capacity)(), u32()
            if self.cg.CGGetDisplayTransferByTable(did, capacity, r, g, b, ctypes.byref(n)) == 0 and n.value >= 2:
                self.originals[did] = (list(r[: n.value]), list(g[: n.value]), list(b[: n.value]))
        color = (
            FeatureStatus.ok("Tabela de transferência (CoreGraphics)")
            if self.originals
            else FeatureStatus.missing("O macOS não permitiu ler a tabela de cor das telas.")
        )
        return Capabilities(
            platform_label="macOS",
            displays=tuple(displays),
            temperature=color,
            soft_dim=color,
            filters=FeatureStatus.missing(
                "O macOS não oferece API pública para filtros de cor de tela inteira.",
                "Use Ajustes do Sistema › Acessibilidade › Tela › Filtros de cor. "
                "Os filtros deste app funcionam na prévia.",
            ),
            notes=("O macOS restaura as cores originais quando o app é fechado.",),
        )

    def read_brightness(self, display_id: str) -> int | None:
        return None

    def set_brightness(self, display_id: str, percent: int) -> None:
        raise UnsupportedError("O macOS não oferece API pública para o brilho de hardware.")

    def _write(self, did: int, channels) -> None:
        n = len(channels[0])
        arrays = [(ctypes.c_float * n)(*ch) for ch in channels]
        if self.cg.CGSetDisplayTransferByTable(did, n, *arrays) != 0:
            raise BackendError("O macOS recusou a nova tabela de cor.")

    def set_color_gains(self, gains) -> None:
        if not self.originals:
            raise UnsupportedError("Ajuste de cor indisponível.")
        with self.lock:
            for did, base in self.originals.items():
                self._write(did, [[min(1.0, v * gain) for v in ch] for ch, gain in zip(base, gains)])

    def set_filter(self, matrix: Matrix3 | None) -> None:
        if matrix is not None:
            raise UnsupportedError("Filtros de tela inteira não são suportados no macOS.")

    def restore_color(self) -> None:
        with self.lock:
            for did, base in self.originals.items():
                self._write(did, base)

    def reset_color_to_linear(self) -> None:
        """Emergência (--reset-colors): o próprio macOS reaplica o perfil ColorSync."""
        self.cg.CGDisplayRestoreColorSyncSettings()
