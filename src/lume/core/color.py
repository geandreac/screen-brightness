"""Matemática de cor: temperatura, curvas de gama e matrizes de filtro.

Tudo aqui é puro (sem I/O) para poder ser testado e reutilizado na prévia.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from lume.core.models import NEUTRAL_K

Matrix3 = tuple[tuple[float, float, float], ...]

IDENTITY: Matrix3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


# ---------------------------------------------------------------- temperatura

def _blackbody_rgb(kelvin: float) -> tuple[float, float, float]:
    """Aproximação de Tanner Helland da cor de um corpo negro (0–1 por canal)."""
    t = kelvin / 100.0
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)
    if t >= 66:
        b = 255.0
    elif t <= 19:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(t - 10) - 305.0447927307
    return tuple(max(0.0, min(255.0, c)) / 255.0 for c in (r, g, b))  # type: ignore[return-value]


_NEUTRAL = _blackbody_rgb(NEUTRAL_K)


def temperature_multipliers(kelvin: int) -> tuple[float, float, float]:
    """Multiplicadores R, G, B relativos a 6500 K (neutro = 1, 1, 1).

    Nunca ultrapassam 1: tons quentes reduzem azul/verde, tons frios reduzem
    vermelho/verde. Assim nada “estoura” e a luminância só diminui.
    """
    if kelvin == NEUTRAL_K:
        return (1.0, 1.0, 1.0)
    raw = [c / n for c, n in zip(_blackbody_rgb(kelvin), _NEUTRAL)]
    peak = max(raw)
    return tuple(round(c / peak, 6) for c in raw)  # type: ignore[return-value]


def temperature_label(kelvin: int) -> str:
    if kelvin < 3000:
        return "Muito quente"
    if kelvin < 5000:
        return "Quente"
    if kelvin < 6200:
        return "Levemente quente"
    if kelvin <= 6800:
        return "Neutra"
    if kelvin <= 8000:
        return "Levemente fria"
    return "Fria"


def channel_gains(temperature: int, soft_dim: int) -> tuple[float, float, float]:
    """Ganho final por canal combinando temperatura e escurecimento por software."""
    dim = soft_dim / 100.0
    return tuple(c * dim for c in temperature_multipliers(temperature))  # type: ignore[return-value]


# ------------------------------------------------------------------- gama

def linear_ramp(size: int, max_value: int = 65535) -> list[int]:
    if size < 2:
        return [max_value] * size
    return [round(i * max_value / (size - 1)) for i in range(size)]


def sane_ramp(ramp: list[int], max_value: int = 65535) -> bool:
    """Uma curva lida do sistema só é confiável se for crescente e terminar alta.

    Alguns drivers (e servidores virtuais) devolvem lixo; usar isso como base
    deixaria a tela ilegível.
    """
    if len(ramp) < 2 or ramp[-1] < max_value // 2:
        return False
    return all(b >= a for a, b in zip(ramp, ramp[1:]))


def sane_ramps(ramps, max_value: int = 65535):
    """Devolve as curvas lidas, ou curvas lineares se alguma for inválida."""
    if all(sane_ramp(list(ch), max_value) for ch in ramps):
        return tuple(list(ch) for ch in ramps)
    size = len(ramps[0])
    return tuple(linear_ramp(size, max_value) for _ in range(3))


def scale_ramp(base: list[int], gain: float, max_value: int = 65535) -> list[int]:
    """Aplica um ganho sobre a curva original (preserva calibração ICC carregada)."""
    return [max(0, min(max_value, round(v * gain))) for v in base]


def build_ramps(
    base: tuple[list[int], list[int], list[int]],
    gains: tuple[float, float, float],
    max_value: int = 65535,
) -> tuple[list[int], list[int], list[int]]:
    return tuple(scale_ramp(ch, g, max_value) for ch, g in zip(base, gains))  # type: ignore[return-value]


# ---------------------------------------------------------------- filtros

# Simulação de Machado, Oliveira & Fernandes (2009), severidade 1.0.
_SIM_PROTAN: Matrix3 = (
    (0.152286, 1.052583, -0.204868),
    (0.114503, 0.786281, 0.099216),
    (-0.003882, -0.048116, 1.051998),
)
_SIM_DEUTAN: Matrix3 = (
    (0.367322, 0.860646, -0.227968),
    (0.280085, 0.672501, 0.047413),
    (-0.011820, 0.042940, 0.968881),
)
_SIM_TRITAN: Matrix3 = (
    (1.255528, -0.076749, -0.178779),
    (-0.078411, 0.930809, 0.147602),
    (0.004733, 0.691367, 0.303900),
)
# Redistribuição do erro (daltonização): desloca a informação perdida
# para canais que ainda são percebidos.
_SHIFT_RED_GREEN: Matrix3 = ((0.0, 0.0, 0.0), (0.7, 1.0, 0.0), (0.7, 0.0, 1.0))
_SHIFT_BLUE_YELLOW: Matrix3 = ((1.0, 0.0, 0.7), (0.0, 1.0, 0.7), (0.0, 0.0, 0.0))


def mat_mul(a: Matrix3, b: Matrix3) -> Matrix3:
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3)
    )


def mat_add(a: Matrix3, b: Matrix3, scale_b: float = 1.0) -> Matrix3:
    return tuple(tuple(a[i][j] + scale_b * b[i][j] for j in range(3)) for i in range(3))


def _daltonize(sim: Matrix3, shift: Matrix3) -> Matrix3:
    # C = I + E·(I − S)
    return mat_add(IDENTITY, mat_mul(shift, mat_add(IDENTITY, sim, -1.0)))


_GRAYSCALE: Matrix3 = ((0.2126, 0.7152, 0.0722),) * 3


@dataclass(frozen=True)
class ColorFilter:
    id: str
    name: str
    description: str
    matrix: Matrix3


FILTERS: dict[str, ColorFilter] = {
    f.id: f
    for f in (
        ColorFilter(
            "red_green_d",
            "Realce vermelho‑verde (tipo deutan)",
            "Desloca diferenças entre vermelho e verde para variações de azul e brilho.",
            _daltonize(_SIM_DEUTAN, _SHIFT_RED_GREEN),
        ),
        ColorFilter(
            "red_green_p",
            "Realce vermelho‑verde (tipo protan)",
            "Variante que também compensa vermelhos que parecem mais escuros.",
            _daltonize(_SIM_PROTAN, _SHIFT_RED_GREEN),
        ),
        ColorFilter(
            "blue_yellow",
            "Realce azul‑amarelo (tipo tritan)",
            "Desloca diferenças entre azul e amarelo para variações de vermelho e verde.",
            _daltonize(_SIM_TRITAN, _SHIFT_BLUE_YELLOW),
        ),
        ColorFilter(
            "grayscale",
            "Tons de cinza",
            "Remove a cor e mantém apenas a luminosidade. Útil para checar contraste.",
            _GRAYSCALE,
        ),
    )
}


def filter_matrix(filter_id: str | None, strength: int) -> Matrix3:
    """Matriz final do filtro, interpolada com a identidade pela intensidade."""
    if filter_id is None or strength <= 0:
        return IDENTITY
    full = FILTERS[filter_id].matrix
    s = max(0, min(100, strength)) / 100.0
    return mat_add(IDENTITY, mat_add(full, IDENTITY, -1.0), s)


def to_color_effect_5x5(m: Matrix3) -> list[float]:
    """Converte para o layout MAGCOLOREFFECT do Windows (vetor‑linha, 5×5)."""
    out = [0.0] * 25
    for i in range(3):
        for j in range(3):
            # Windows calcula [r g b a 1] · M, então a matriz vai transposta.
            out[j * 5 + i] = float(m[i][j])
    out[3 * 5 + 3] = 1.0
    out[4 * 5 + 4] = 1.0
    return out


# ---------------------------------------------------------------- prévia

def transform_rgb(
    rgb: tuple[int, int, int],
    gains: tuple[float, float, float],
    matrix: Matrix3 = IDENTITY,
) -> tuple[int, int, int]:
    """Aplica filtro e depois ganho por canal, na mesma ordem do pipeline real
    (o filtro de tela inteira atua sobre a imagem, a curva de gama na saída)."""
    r, g, b = (c / 255.0 for c in rgb)
    mixed = [matrix[i][0] * r + matrix[i][1] * g + matrix[i][2] * b for i in range(3)]
    return tuple(  # type: ignore[return-value]
        max(0, min(255, round(min(1.0, max(0.0, c)) * gain * 255))) for c, gain in zip(mixed, gains)
    )
