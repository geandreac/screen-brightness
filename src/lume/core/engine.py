"""Aplicação de ajustes em segundo plano, com transições graduais.

Chamadas ao hardware (DDC/CI, WMI, D‑Bus) podem levar centenas de
milissegundos; por isso rodam numa thread própria. Pedidos novos substituem
os antigos (o mais recente vence), então arrastar um controle nunca cria fila.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from lume.core.color import channel_gains, filter_matrix
from lume.core.errors import BackendError, UnsupportedError
from lume.core.models import Adjustments, Capabilities
from lume.platform.base import DisplayBackend


@dataclass(frozen=True)
class FeatureError:
    feature: str  # "brightness" | "color" | "filter"
    display_id: str | None
    error: BackendError


@dataclass(frozen=True)
class ApplyResult:
    requested: Adjustments
    actual: Adjustments
    errors: tuple[FeatureError, ...] = ()
    completed: bool = True  # False quando um pedido mais novo interrompeu este


# ---------------------------------------------------------------- interpolação

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ease(t: float) -> float:
    """Suavização simples (ease‑in‑out) para evitar arrancos."""
    return t * t * (3 - 2 * t)


def interpolate(a: Adjustments, b: Adjustments, t: float) -> Adjustments:
    if t >= 1:
        return b
    brightness = {
        key: round(_lerp(a.brightness.get(key, value), value, t)) for key, value in b.brightness.items()
    }
    # Interpola em mired (1e6/K): passos perceptualmente mais uniformes.
    mired = _lerp(1e6 / a.temperature, 1e6 / b.temperature, t)
    temperature = round(1e6 / mired)
    soft_dim = round(_lerp(a.soft_dim, b.soft_dim, t))

    a_strength = a.filter_strength if a.filter_id else 0
    b_strength = b.filter_strength if b.filter_id else 0
    if a.filter_id == b.filter_id or a.filter_id is None or b.filter_id is None:
        filter_id = b.filter_id or a.filter_id
        strength = round(_lerp(a_strength, b_strength, t))
    elif t < 0.5:  # troca de filtro: some o antigo, depois surge o novo
        filter_id, strength = a.filter_id, round(a_strength * (1 - 2 * t))
    else:
        filter_id, strength = b.filter_id, round(b_strength * (2 * t - 1))
    return Adjustments(brightness, temperature, soft_dim, filter_id, strength)


# ---------------------------------------------------------------- aplicador

class Applier:
    """Envia ao backend só o que mudou e acompanha o que de fato está na tela."""

    def __init__(self, backend: DisplayBackend, caps: Capabilities, current: Adjustments):
        self.backend = backend
        self.caps = caps
        self.current = current

    def apply(
        self,
        target: Adjustments,
        *,
        final: bool = True,
        frame: int = 1,
        frames: int = 1,
        skip: set[tuple[str, str | None]] | None = None,
    ) -> list[FeatureError]:
        skip = skip if skip is not None else set()
        errors: list[FeatureError] = []
        state = self.current

        for display_id, value in target.brightness.items():
            if state.brightness.get(display_id) == value or ("brightness", display_id) in skip:
                continue
            info = self.caps.display(display_id)
            if info is None or not info.brightness.available:
                continue  # sem controle de hardware: o valor fica só como preferência salva
            if not final:
                if info.brightness_steps <= 0:
                    continue
                stride = max(1, frames // info.brightness_steps)
                if frame % stride:
                    continue
            try:
                self.backend.set_brightness(display_id, value)
                state = state.with_brightness(display_id, value)
            except BackendError as exc:
                skip.add(("brightness", display_id))
                errors.append(FeatureError("brightness", display_id, exc))

        if (target.temperature, target.soft_dim) != (state.temperature, state.soft_dim) and (
            "color", None
        ) not in skip:
            try:
                if not (self.caps.temperature.available or self.caps.soft_dim.available):
                    raise UnsupportedError(
                        self.caps.temperature.reason or "Ajuste de cor indisponível.",
                        self.caps.temperature.hint,
                    )
                self.backend.set_color_gains(channel_gains(target.temperature, target.soft_dim))
                state = state.with_(temperature=target.temperature, soft_dim=target.soft_dim)
            except BackendError as exc:
                skip.add(("color", None))
                errors.append(FeatureError("color", None, exc))

        want = (target.filter_id, target.filter_strength) if target.filter_active else None
        have = (state.filter_id, state.filter_strength) if state.filter_active else None
        if want != have and ("filter", None) not in skip:
            try:
                if want is not None and not self.caps.filters.available:
                    raise UnsupportedError(
                        self.caps.filters.reason or "Filtros indisponíveis.", self.caps.filters.hint
                    )
                matrix = filter_matrix(*want) if want else None
                self.backend.set_filter(matrix)
                state = state.with_(filter_id=target.filter_id, filter_strength=target.filter_strength)
            except BackendError as exc:
                skip.add(("filter", None))
                errors.append(FeatureError("filter", None, exc))

        if final and not errors:
            # Normaliza campos sem efeito (ex.: intensidade com filtro desligado).
            state = state.with_(filter_id=target.filter_id, filter_strength=target.filter_strength)
        self.current = state
        return errors


# ---------------------------------------------------------------- motor

class ApplyEngine:
    def __init__(
        self,
        applier: Applier,
        on_result: Callable[[ApplyResult], None],
        *,
        duration: float = 0.45,
        fps: int = 30,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.applier = applier
        self.on_result = on_result
        self.duration = duration
        self.fps = fps
        self._sleep = sleep
        self._cond = threading.Condition()
        self._pending: tuple[Adjustments, bool] | None = None
        self._busy = False
        self._stopped = False
        self._thread = threading.Thread(target=self._run, name="lume-apply", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def request(self, target: Adjustments, animate: bool) -> None:
        with self._cond:
            self._pending = (target, animate)
            self._cond.notify_all()

    def wait_idle(self, timeout: float = 5.0) -> bool:
        end = time.monotonic() + timeout
        with self._cond:
            while self._pending is not None or self._busy:
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self._cond.wait(left)
        return True

    def stop(self, timeout: float = 3.0) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def _has_newer(self) -> bool:
        with self._cond:
            return self._pending is not None or self._stopped

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._pending is None and not self._stopped:
                    self._cond.wait()
                if self._stopped:
                    return
                target, animate = self._pending  # type: ignore[misc]
                self._pending = None
                self._busy = True
            try:
                result = self.execute(target, animate)
                self.on_result(result)
            finally:
                with self._cond:
                    self._busy = False
                    self._cond.notify_all()

    def execute(self, target: Adjustments, animate: bool) -> ApplyResult:
        start = self.applier.current
        frames = max(1, round(self.duration * self.fps)) if animate else 1
        skip: set[tuple[str, str | None]] = set()
        errors: list[FeatureError] = []
        for i in range(1, frames + 1):
            final = i == frames
            if not final and self._has_newer():
                return ApplyResult(target, self.applier.current, tuple(errors), completed=False)
            state = target if final else interpolate(start, target, ease(i / frames))
            errors += self.applier.apply(state, final=final, frame=i, frames=frames, skip=skip)
            if not final:
                self._sleep(1 / self.fps)
        return ApplyResult(target, self.applier.current, tuple(errors))
