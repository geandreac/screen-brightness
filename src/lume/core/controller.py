"""Orquestra estado original, alvo e aplicado, sem depender da interface."""

from __future__ import annotations

from typing import Callable

from lume.core.engine import Applier, ApplyEngine, ApplyResult
from lume.core.errors import BackendError
from lume.core.models import Adjustments, Capabilities
from lume.platform.base import DisplayBackend


class Controller:
    def __init__(
        self,
        backend: DisplayBackend,
        on_result: Callable[[ApplyResult], None] | None = None,
        *,
        duration: float = 0.45,
        sleep=None,
    ):
        self.backend = backend
        self.on_result = on_result or (lambda result: None)
        self._duration = duration
        self._sleep = sleep
        self.caps: Capabilities | None = None
        self.original = Adjustments()
        self.target = Adjustments()
        self.engine: ApplyEngine | None = None
        self.comparing = False

    # Pode demorar (DDC/CI): a interface chama isto fora da thread principal.
    def initialize(self) -> Capabilities:
        caps = self.backend.probe()
        brightness: dict[str, int] = {}
        for display in caps.displays:
            if not display.brightness.available:
                continue
            try:
                value = self.backend.read_brightness(display.id)
            except BackendError:
                value = None
            if value is not None:
                brightness[display.id] = value
        self.caps = caps
        self.original = Adjustments(brightness=brightness)
        self.target = self.original
        applier = Applier(self.backend, caps, self.original)
        kwargs = {"duration": self._duration}
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        self.engine = ApplyEngine(applier, lambda result: self.on_result(result), **kwargs)
        self.engine.start()
        return caps

    @property
    def applied(self) -> Adjustments:
        return self.engine.applier.current if self.engine else self.original

    def request(self, target: Adjustments, *, animate: bool) -> None:
        assert self.engine is not None, "initialize() precisa rodar antes"
        self.target = target
        if not self.comparing:
            self.engine.request(target, animate)

    def reconcile(self, result: ApplyResult) -> Adjustments:
        """Depois de uma falha, o alvo passa a refletir o que de fato está na tela."""
        target, actual = self.target, result.actual
        for err in result.errors:
            if err.feature == "color":
                target = target.with_(temperature=actual.temperature, soft_dim=actual.soft_dim)
            elif err.feature == "filter":
                target = target.with_(filter_id=actual.filter_id, filter_strength=actual.filter_strength)
            elif err.feature == "brightness" and err.display_id in actual.brightness:
                target = target.with_brightness(err.display_id, actual.brightness[err.display_id])
        self.target = target
        return target

    def restore_original(self, *, animate: bool) -> Adjustments:
        self.comparing = False
        self.request(self.original, animate=animate)
        return self.original

    def compare(self, active: bool) -> None:
        """Mostra temporariamente as cores originais sem perder os ajustes."""
        if self.engine is None or active == self.comparing:
            return
        self.comparing = active
        shown = self.target.color_only_original() if active else self.target
        self.engine.request(shown, False)

    def shutdown(self, *, restore_color: bool = True) -> None:
        if self.engine is not None:
            self.engine.stop()
        if restore_color:
            try:
                self.backend.restore_color()
            except BackendError:
                pass
        self.backend.close()
