"""Contrato que cada plataforma implementa.

A interface nunca fala direto com o sistema: tudo passa por um backend, e
todo backend precisa declarar honestamente o que suporta em ``probe()``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from lume.core.color import Matrix3
from lume.core.models import Capabilities


class DisplayBackend(ABC):
    @abstractmethod
    def probe(self) -> Capabilities:
        """Detecta telas e recursos. Pode ser lento (DDC/CI), não chame na thread da UI."""

    @abstractmethod
    def read_brightness(self, display_id: str) -> int | None:
        """Brilho atual em %, ou ``None`` se não for legível."""

    @abstractmethod
    def set_brightness(self, display_id: str, percent: int) -> None:
        """Altera o brilho de hardware (luz de fundo ou DDC/CI)."""

    @abstractmethod
    def set_color_gains(self, gains: tuple[float, float, float]) -> None:
        """Aplica ganhos R, G, B sobre a curva de gama original de todas as telas."""

    @abstractmethod
    def set_filter(self, matrix: Matrix3 | None) -> None:
        """Ativa (matriz) ou desativa (``None``) o filtro de cor de tela inteira."""

    @abstractmethod
    def restore_color(self) -> None:
        """Volta exatamente às curvas de cor capturadas na inicialização e desliga filtros."""

    def close(self) -> None:
        """Libera recursos do sistema."""
