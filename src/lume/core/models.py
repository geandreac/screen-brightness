"""Modelos imutáveis compartilhados entre plataforma, motor e interface."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

NEUTRAL_K = 6500
MIN_K = 1900
MAX_K = 10000
# Escurecimento por software nunca chega a 0 % para a tela não ficar preta.
MIN_SOFT_DIM = 20


@dataclass(frozen=True)
class FeatureStatus:
    """Estado de um recurso: disponível ou não, por qual método e por quê."""

    available: bool
    method: str = ""
    reason: str = ""
    hint: str = ""

    @classmethod
    def ok(cls, method: str) -> "FeatureStatus":
        return cls(True, method=method)

    @classmethod
    def missing(cls, reason: str, hint: str = "") -> "FeatureStatus":
        return cls(False, reason=reason, hint=hint)


@dataclass(frozen=True)
class DisplayInfo:
    id: str
    name: str
    internal: bool
    brightness: FeatureStatus
    brightness_min: int = 0
    # Quantos passos intermediários o hardware aceita numa transição (0 = só o valor final).
    brightness_steps: int = 0


@dataclass(frozen=True)
class Capabilities:
    platform_label: str
    displays: tuple[DisplayInfo, ...]
    temperature: FeatureStatus
    soft_dim: FeatureStatus
    filters: FeatureStatus
    notes: tuple[str, ...] = ()
    simulated: bool = False

    def display(self, display_id: str) -> DisplayInfo | None:
        return next((d for d in self.displays if d.id == display_id), None)


@dataclass(frozen=True)
class Adjustments:
    """Estado completo desejado (ou aplicado) da tela.

    Brilho, temperatura, escurecimento e filtro são independentes entre si.
    """

    brightness: dict[str, int] = field(default_factory=dict)
    temperature: int = NEUTRAL_K
    soft_dim: int = 100
    filter_id: str | None = None
    filter_strength: int = 100

    def with_(self, **changes) -> "Adjustments":
        if "brightness" in changes:
            changes["brightness"] = dict(changes["brightness"])
        return replace(self, **changes)

    def with_brightness(self, display_id: str, value: int) -> "Adjustments":
        values = dict(self.brightness)
        values[display_id] = value
        return replace(self, brightness=values)

    @property
    def filter_active(self) -> bool:
        return self.filter_id is not None and self.filter_strength > 0

    @property
    def color_neutral(self) -> bool:
        return self.temperature == NEUTRAL_K and self.soft_dim == 100 and not self.filter_active

    def color_only_original(self) -> "Adjustments":
        """Mesmo brilho de hardware, mas cores originais (usado em “Comparar”)."""
        return replace(self, temperature=NEUTRAL_K, soft_dim=100, filter_id=None)

    def to_dict(self) -> dict:
        return {
            "brightness": dict(self.brightness),
            "temperature": self.temperature,
            "soft_dim": self.soft_dim,
            "filter_id": self.filter_id,
            "filter_strength": self.filter_strength,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Adjustments":
        from lume.core.color import FILTERS

        def clamp(value, low, high, default):
            try:
                return max(low, min(high, int(value)))
            except (TypeError, ValueError):
                return default

        brightness = {}
        raw = data.get("brightness") or {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                brightness[str(key)] = clamp(value, 0, 100, 100)
        filter_id = data.get("filter_id")
        if filter_id not in FILTERS:
            filter_id = None
        return cls(
            brightness=brightness,
            temperature=clamp(data.get("temperature"), MIN_K, MAX_K, NEUTRAL_K),
            soft_dim=clamp(data.get("soft_dim"), MIN_SOFT_DIM, 100, 100),
            filter_id=filter_id,
            filter_strength=clamp(data.get("filter_strength"), 0, 100, 100),
        )
