"""Backend simulado: usado nos testes e no modo demonstração (``--demo``).

Nunca altera a tela de verdade, e a interface deixa isso explícito.
"""

from __future__ import annotations

import threading

from lume.core.color import Matrix3
from lume.core.errors import BackendError, UnsupportedError
from lume.core.models import Capabilities, DisplayInfo, FeatureStatus
from lume.platform.base import DisplayBackend


class MockBackend(DisplayBackend):
    def __init__(
        self,
        *,
        displays: tuple[DisplayInfo, ...] | None = None,
        brightness: dict[str, int] | None = None,
        color: bool = True,
        filters: bool = True,
        fail: set[str] | None = None,
        label: str = "Modo demonstração",
    ):
        self.displays = displays or (
            DisplayInfo("internal", "Tela integrada", True, FeatureStatus.ok("Simulado"), 1, 8),
            DisplayInfo(
                "external",
                "Monitor externo",
                False,
                FeatureStatus.missing(
                    "Este monitor não respondeu ao DDC/CI.",
                    "Ative DDC/CI no menu do próprio monitor ou use o escurecimento por software.",
                ),
            ),
        )
        self.brightness = dict(brightness or {"internal": 70})
        self.color = color
        self.filters = filters
        self.fail = set(fail or ())
        self.label = label
        self.gains = (1.0, 1.0, 1.0)
        self.matrix: Matrix3 | None = None
        self.calls: list[tuple] = []
        self.restored = 0
        self._lock = threading.Lock()

    def probe(self) -> Capabilities:
        def status(ok: bool, method: str) -> FeatureStatus:
            return FeatureStatus.ok(method) if ok else FeatureStatus.missing(
                "Recurso indisponível nesta configuração simulada."
            )

        return Capabilities(
            platform_label=self.label,
            displays=self.displays,
            temperature=status(self.color, "Curva de gama (simulada)"),
            soft_dim=status(self.color, "Curva de gama (simulada)"),
            filters=status(self.filters, "Matriz de cor (simulada)"),
            simulated=True,
        )

    def _check(self, op: str) -> None:
        if op in self.fail:
            raise BackendError(f"Falha simulada em “{op}”.", "Tente novamente.")

    def read_brightness(self, display_id: str) -> int | None:
        return self.brightness.get(display_id)

    def set_brightness(self, display_id: str, percent: int) -> None:
        info = next((d for d in self.displays if d.id == display_id), None)
        if info is None or not info.brightness.available:
            raise UnsupportedError("Brilho de hardware indisponível para esta tela.")
        self._check("brightness")
        with self._lock:
            self.brightness[display_id] = percent
            self.calls.append(("brightness", display_id, percent))

    def set_color_gains(self, gains: tuple[float, float, float]) -> None:
        if not self.color:
            raise UnsupportedError("Curva de gama indisponível.")
        self._check("color")
        with self._lock:
            self.gains = gains
            self.calls.append(("color", gains))

    def set_filter(self, matrix: Matrix3 | None) -> None:
        if not self.filters and matrix is not None:
            raise UnsupportedError("Filtros de tela inteira indisponíveis.")
        self._check("filter")
        with self._lock:
            self.matrix = matrix
            self.calls.append(("filter", matrix))

    def restore_color(self) -> None:
        with self._lock:
            self.gains = (1.0, 1.0, 1.0)
            self.matrix = None
            self.restored += 1
            self.calls.append(("restore",))
