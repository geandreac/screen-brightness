"""Prévia lado a lado: “Original” e “Com ajustes”.

Usa a mesma matemática do pipeline real (``lume.core.color``), por isso
funciona mesmo quando o sistema não permite aplicar o ajuste à tela.
"""

from __future__ import annotations

import colorsys

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from lume.core.color import IDENTITY, Matrix3, transform_rgb

SWATCHES = [
    (213, 43, 30), (46, 160, 67), (36, 99, 235), (250, 204, 21),
    (234, 88, 12), (147, 51, 234), (20, 184, 166), (120, 72, 40),
]
SKIN_AND_NATURE = [(241, 194, 125), (198, 134, 66), (141, 85, 36), (88, 129, 87), (163, 177, 138), (153, 27, 27)]


class PreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.gains = (1.0, 1.0, 1.0)
        self.matrix: Matrix3 = IDENTITY
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("Prévia de cores")
        self.setAccessibleDescription(
            "Amostra de cores à esquerda sem ajustes e à direita com os ajustes escolhidos."
        )

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(420, self._height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(260, self._height())

    def _height(self) -> int:
        return round(self.fontMetrics().height() * 9.5)

    def set_effect(self, gains, matrix: Matrix3) -> None:
        self.gains, self.matrix = tuple(gains), matrix
        self.update()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        self.setFixedHeight(self._height())

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        gap = 12
        caption_h = self.fontMetrics().height() + 6
        half = (self.width() - gap) / 2
        for i, (title, gains, matrix) in enumerate(
            (("Original", (1.0, 1.0, 1.0), IDENTITY), ("Com ajustes", self.gains, self.matrix))
        ):
            x = i * (half + gap)
            p.setPen(self.palette().windowText().color())
            p.drawText(QRectF(x, 0, half, caption_h), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
            self._paint_sample(p, QRectF(x, caption_h, half, self.height() - caption_h - 1), gains, matrix)
        p.end()

    def _paint_sample(self, p: QPainter, r: QRectF, gains, matrix) -> None:
        def color(rgb) -> QColor:
            return QColor(*transform_rgb(rgb, gains, matrix))

        p.save()
        p.setPen(QPen(self.palette().mid().color(), 1))
        p.setBrush(color((255, 255, 255)))
        p.drawRoundedRect(r, 8, 8)
        pad = 8
        inner = r.adjusted(pad, pad, -pad, -pad)
        p.setPen(Qt.PenStyle.NoPen)
        rows = 4
        row_h = (inner.height() - (rows - 1) * 5) / rows

        # 1) espectro de matizes
        slices = 48
        w = inner.width() / slices
        for k in range(slices):
            rgb = tuple(round(c * 255) for c in colorsys.hsv_to_rgb(k / slices, 0.85, 0.95))
            p.setBrush(color(rgb))
            p.drawRect(QRectF(inner.left() + k * w, inner.top(), w + 0.6, row_h))

        # 2) cores primárias e secundárias
        y = inner.top() + row_h + 5
        w = inner.width() / len(SWATCHES)
        for k, rgb in enumerate(SWATCHES):
            p.setBrush(color(rgb))
            p.drawRect(QRectF(inner.left() + k * w + 1, y, w - 2, row_h))

        # 3) pele, natureza e um vermelho escuro (pares comuns de confusão)
        y += row_h + 5
        w = inner.width() / len(SKIN_AND_NATURE)
        for k, rgb in enumerate(SKIN_AND_NATURE):
            p.setBrush(color(rgb))
            p.drawRect(QRectF(inner.left() + k * w + 1, y, w - 2, row_h))

        # 4) escala de cinza + texto
        y += row_h + 5
        steps = 8
        w = inner.width() * 0.6 / steps
        for k in range(steps):
            v = round(k * 255 / (steps - 1))
            p.setBrush(color((v, v, v)))
            p.drawRect(QRectF(inner.left() + k * w, y, w + 0.6, row_h))
        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(color((24, 24, 27)))
        p.drawText(
            QRectF(inner.left() + inner.width() * 0.62, y, inner.width() * 0.38, row_h),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Texto Aa",
        )
        p.restore()
