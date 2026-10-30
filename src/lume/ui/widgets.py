"""Componentes reutilizáveis. Estados sempre têm texto, não só cor."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def label(text: str = "", role: str | None = None, *, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    if wrap:
        lbl.setWordWrap(True)
        lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    return lbl


def button(text: str, kind: str | None = None, *, tip: str = "") -> QPushButton:
    btn = QPushButton(text)
    if kind:
        btn.setProperty("kind", kind)
    if tip:
        btn.setToolTip(tip)
        btn.setAccessibleDescription(tip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def restyle(widget: QWidget) -> None:
    """Reaplica o estilo depois de mudar uma propriedade dinâmica."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class StatusPill(QLabel):
    """Indicador de estado com símbolo + texto (nunca depende só da cor)."""

    SYMBOLS = {"ok": "✓", "active": "●", "off": "○", "warn": "⚠", "error": "✕"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_state(self, kind: str, text: str) -> None:
        self.setProperty("pill", kind)
        self.setText(f"{self.SYMBOLS.get(kind, '')} {text}".strip())
        self.setAccessibleName(f"Estado: {text}")
        restyle(self)


class Card(QWidget):
    """Seção agrupada por finalidade: título e estado acima, painel com o conteúdo.

    O título fica fora do painel (como num grupo de ajustes), o que deixa os
    painéis leves e a hierarquia clara sem precisar de mais divisórias.
    """

    def __init__(self, title: str, description: str = "", parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 2, 0)
        head.setSpacing(8)
        self.title = label(title, "section")
        self.title.setAccessibleName(title)
        self.pill = StatusPill()
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.pill)
        outer.addLayout(head)
        self.surface = QFrame()
        self.surface.setProperty("role", "card")
        self.surface.setFrameShape(QFrame.Shape.NoFrame)
        inner = QVBoxLayout(self.surface)
        inner.setContentsMargins(16, 14, 16, 16)
        inner.setSpacing(12)
        self.description = label(description, "help", wrap=True)
        self.description.setVisible(bool(description))
        inner.addWidget(self.description)
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        inner.addLayout(self.body)
        outer.addWidget(self.surface)
        self.setAccessibleName(title)


def unavailable(text: str) -> QLabel:
    """Recurso incompatível: painel tracejado + símbolo + texto (não só cor)."""
    lbl = label("⊘  " + text, "unavailable", wrap=True)
    lbl.setAccessibleName(text)
    return lbl


def divider() -> QFrame:
    line = QFrame()
    line.setProperty("role", "divider")
    line.setFrameShape(QFrame.Shape.NoFrame)
    return line


class ValueSlider(QWidget):
    """Controle deslizante com rótulo, valor numérico editável e legendas nas pontas.

    ``valueChanged(int, bool)``: o segundo argumento indica se a pessoa ainda
    está arrastando (para não animar durante o arraste).
    """

    valueChanged = Signal(int, bool)

    def __init__(
        self,
        title: str,
        minimum: int,
        maximum: int,
        value: int,
        *,
        unit: str = "%",
        step: int = 1,
        page: int = 10,
        left_caption: str = "",
        right_caption: str = "",
        describe=None,
        track: str | None = None,
        help_text: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._describe = describe or (lambda v: "")
        self._unit = unit
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        top = QHBoxLayout()
        self.title = label(title, "label-strong")
        self.detail = label("", "caption")
        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(f" {unit}")
        self.spin.setAccessibleName(f"{title}, valor exato")
        self.spin.setKeyboardTracking(False)
        self.spin.setMinimumWidth(84)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        top.addWidget(self.title)
        top.addSpacing(6)
        top.addWidget(self.detail)
        top.addStretch(1)
        top.addWidget(self.spin)
        layout.addLayout(top)

        if help_text:
            self.help = label(help_text, "help", wrap=True)
            layout.addWidget(self.help)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setSingleStep(step)
        self.slider.setPageStep(page)
        self.slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.slider.setAccessibleName(title)
        if track:
            self.slider.setProperty("track", track)
        layout.addWidget(self.slider)

        if left_caption or right_caption:
            ends = QHBoxLayout()
            ends.addWidget(label(left_caption, "caption"))
            ends.addStretch(1)
            ends.addWidget(label(right_caption, "caption"))
            layout.addLayout(ends)

        self.title.setBuddy(self.slider)
        self.set_value(value)
        self.slider.valueChanged.connect(self._from_slider)
        self.slider.sliderReleased.connect(lambda: self.valueChanged.emit(self.slider.value(), False))
        self.spin.valueChanged.connect(self._from_spin)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, value: int) -> None:
        for w in (self.slider, self.spin):
            w.blockSignals(True)
            w.setValue(value)
            w.blockSignals(False)
        self._update_text(value)

    def _update_text(self, value: int) -> None:
        detail = self._describe(value)
        self.detail.setText(detail)
        spoken = f"{value} {self._unit}" + (f", {detail}" if detail else "")
        self.slider.setAccessibleDescription(spoken)

    def _from_slider(self, value: int) -> None:
        self.spin.blockSignals(True)
        self.spin.setValue(value)
        self.spin.blockSignals(False)
        self._update_text(value)
        self.valueChanged.emit(value, self.slider.isSliderDown())

    def _from_spin(self, value: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(value)
        self.slider.blockSignals(False)
        self._update_text(value)
        self.valueChanged.emit(value, False)


class Banner(QFrame):
    """Faixa de aviso inline (não modal) com ações opcionais."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("banner", "info")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(10)
        self.text = label("", None, wrap=True)
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        layout.addLayout(self.actions)
        self.hide()

    def show_message(self, kind: str, text: str, actions: list[QPushButton] | None = None) -> None:
        self.setProperty("banner", kind)
        prefix = {"warn": "⚠ ", "error": "✕ ", "info": "ⓘ "}.get(kind, "")
        self.text.setText(prefix + text)
        self.setAccessibleName(text)
        while self.actions.count():
            item = self.actions.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for btn in actions or []:
            self.actions.addWidget(btn)
        restyle(self)
        for child in self.findChildren(QLabel):
            restyle(child)
        self.show()


def app_icon() -> QIcon:
    """Ícone próprio: círculo dividido entre um tom quente e um frio."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = size * 0.06
        r = size - 2 * m
        circle = QPainterPath()
        circle.addEllipse(m, m, r, r)
        p.setClipPath(circle)
        p.fillRect(pix.rect(), QColor("#4C7FE0"))
        warm = QPainterPath()
        warm.moveTo(0, 0)
        warm.lineTo(size, 0)
        warm.lineTo(0, size)
        warm.closeSubpath()
        p.fillPath(warm, QColor("#F2A65A"))
        p.setClipping(False)
        p.setPen(QColor(255, 255, 255, 230))
        p.setBrush(QColor(255, 255, 255, 235))
        c = size * 0.2
        p.drawEllipse(size / 2 - c / 2, size / 2 - c / 2, c, c)
        p.end()
        icon.addPixmap(pix)
    return icon
