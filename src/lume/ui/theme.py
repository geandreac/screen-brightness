"""Tokens visuais e folha de estilo (somente apresentação).

Regras compartilhadas:
* Base escura com três níveis de superfície próximos e distinguíveis
  (fundo → painel → elemento elevado), separados por bordas de 1 px.
  Sem transparência atrás de texto e sem sombras decorativas.
* Destaque azul só para ação principal, seleção e foco. Estados sempre têm
  texto e símbolo, nunca só cor.
* Espaçamento em múltiplos de 4 px; raios: 6 (campos/botões), 10 (painéis).
* Tipografia: Inter (SIL OFL 1.1, distribuída com o app em assets/fonts) para
  ter a mesma aparência em todas as plataformas; se não carregar, volta à
  fonte do sistema. Hierarquia por tamanho e peso (400/600), sem texto
  auxiliar menor que o corpo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
FONT_FILES = ("Inter-Regular.ttf", "Inter-SemiBold.ttf")
_ui_family: str | None = None


@dataclass(frozen=True)
class Tokens:
    bg: str
    surface: str
    raised: str
    hover: str
    border: str
    border_strong: str
    text: str
    text_secondary: str
    accent: str
    accent_hover: str
    accent_text: str
    accent_soft: str
    focus: str
    ok_bg: str
    ok_text: str
    warn_bg: str
    warn_border: str
    warn_text: str
    info_bg: str
    info_border: str
    info_text: str
    error_bg: str
    error_border: str
    error_text: str
    neutral_bg: str
    groove: str


# Contrastes (WCAG 2.x) medidos sobre ``surface`` (#1D2024):
# text 14.6:1 · text_secondary 7.4:1 · accent 6.6:1 · accent_text sobre accent 7.0:1.
DARK = Tokens(
    bg="#131518",
    surface="#1D2024",
    raised="#262A2F",
    hover="#2E3339",
    border="#30353C",
    border_strong="#4A515B",
    text="#EDEFF2",
    text_secondary="#A9B0BB",
    accent="#6FA3FF",
    accent_hover="#8DB6FF",
    accent_text="#0A1730",
    accent_soft="#1F3354",
    focus="#9CC0FF",
    ok_bg="#183323",
    ok_text="#9FE3B4",
    warn_bg="#33290F",
    warn_border="#5E4A17",
    warn_text="#F5D68A",
    info_bg="#18263D",
    info_border="#2C4670",
    info_text="#CFE0FF",
    error_bg="#3A1C1E",
    error_border="#6B3034",
    error_text="#FFCDCF",
    neutral_bg="#2A2E34",
    groove="#3A4048",
)


def base_point_size() -> float:
    size = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).pointSizeF()
    return size if size > 0 else 10.0


def apply_palette(app, t: Tokens) -> None:
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.bg,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.raised,
        QPalette.ColorRole.AlternateBase: t.surface,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.raised,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: t.accent_text,
        QPalette.ColorRole.ToolTipBase: t.raised,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.PlaceholderText: t.text_secondary,
        QPalette.ColorRole.Link: t.accent,
        QPalette.ColorRole.Mid: t.border_strong,
        QPalette.ColorRole.Light: t.hover,
        QPalette.ColorRole.Dark: t.bg,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.text_secondary))
    app.setPalette(pal)


def ui_family() -> str | None:
    """Registra a Inter uma única vez; devolve a família ou ``None`` (usa a do sistema)."""
    global _ui_family
    if _ui_family is None:
        families: set[str] = set()
        for name in FONT_FILES:
            font_id = QFontDatabase.addApplicationFont(str(FONT_DIR / name))
            if font_id >= 0:
                families.update(QFontDatabase.applicationFontFamilies(font_id))
        _ui_family = "Inter" if "Inter" in families else ""
    return _ui_family or None


def apply_font(app, scale: int) -> float:
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    family = ui_family()
    if family:
        fallback = font.family()
        font = QFont(family)
        font.setFamilies([family, fallback])  # glifos ausentes caem na fonte do sistema
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    size = base_point_size() * scale / 100
    font.setPointSizeF(size)
    app.setFont(font)
    return size


def stylesheet(t: Tokens, pt: float) -> str:
    """``pt`` é o tamanho base já escalado; medidas em px acompanham a escala."""
    s = pt / 10.0

    def px(value: float) -> str:
        return f"{max(1, round(value * s))}px"

    chip = f"border-radius: {px(10)}; padding: {px(2)} {px(9)}; font-weight: 600;"
    return f"""
    QMainWindow, QDialog, QMessageBox, QInputDialog {{ background: {t.bg}; }}
    QScrollArea, QWidget#content {{ background: {t.bg}; border: none; }}
    QWidget {{ color: {t.text}; }}

    /* ---- tipografia ---- */
    QLabel[role="title"] {{ font-size: {pt * 1.5:.1f}pt; font-weight: 600; }}
    QLabel[role="subtitle"] {{ color: {t.text_secondary}; }}
    QLabel[role="section"] {{ font-size: {pt * 1.08:.1f}pt; font-weight: 600; }}
    QLabel[role="label"] {{ font-weight: 600; }}
    QLabel[role="label-strong"] {{ font-size: {pt * 1.08:.1f}pt; font-weight: 600; }}
    QLabel[role="help"], QLabel[role="caption"] {{ color: {t.text_secondary}; }}
    QLabel[role="unavailable"] {{ color: {t.text_secondary}; background: {t.neutral_bg};
        border: 1px dashed {t.border_strong}; border-radius: {px(6)}; padding: {px(8)} {px(10)}; }}

    /* ---- painéis ---- */
    QFrame[role="card"] {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {px(10)}; }}
    QFrame[role="card"] QLabel {{ background: transparent; }}
    QFrame[role="card"] QLabel[role="unavailable"] {{ background: {t.neutral_bg}; }}
    QFrame[role="divider"] {{ background: {t.border}; max-height: 1px; min-height: 1px; border: none; }}
    QFrame#footer {{ background: {t.surface}; border-top: 1px solid {t.border}; }}
    QFrame#loading {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {px(10)}; }}

    /* ---- indicadores de estado (símbolo + texto, mesmo formato para todos) ---- */
    QLabel[pill] {{ {chip} }}
    QLabel[pill="ok"] {{ color: {t.ok_text}; background: {t.ok_bg}; }}
    QLabel[pill="active"] {{ color: {t.info_text}; background: {t.info_bg}; }}
    QLabel[pill="off"] {{ color: {t.text_secondary}; background: {t.neutral_bg}; }}
    QLabel[pill="warn"] {{ color: {t.warn_text}; background: {t.warn_bg}; }}
    QLabel[pill="error"] {{ color: {t.error_text}; background: {t.error_bg}; }}

    /* ---- avisos ---- */
    QFrame[banner] {{ border-radius: {px(10)}; }}
    QFrame[banner="info"] {{ background: {t.info_bg}; border: 1px solid {t.info_border}; }}
    QFrame[banner="info"] QLabel {{ color: {t.info_text}; }}
    QFrame[banner="warn"] {{ background: {t.warn_bg}; border: 1px solid {t.warn_border}; }}
    QFrame[banner="warn"] QLabel {{ color: {t.warn_text}; }}
    QFrame[banner="error"] {{ background: {t.error_bg}; border: 1px solid {t.error_border}; }}
    QFrame[banner="error"] QLabel {{ color: {t.error_text}; }}
    QFrame[banner] QLabel {{ background: transparent; }}

    /* ---- botões ---- */
    QPushButton {{
        background: {t.raised}; color: {t.text}; border: 1px solid {t.border_strong};
        border-radius: {px(6)}; padding: {px(5)} {px(14)}; min-height: {px(22)};
    }}
    QPushButton:hover {{ background: {t.hover}; }}
    QPushButton:pressed, QPushButton:checked {{ background: {t.accent_soft}; border-color: {t.accent}; }}
    QPushButton:focus {{ border: 2px solid {t.focus}; padding: {px(4)} {px(13)}; }}
    QPushButton:disabled {{ color: {t.text_secondary}; background: {t.surface}; border: 1px dashed {t.border_strong}; }}
    QPushButton[kind="primary"] {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; font-weight: 600; }}
    QPushButton[kind="primary"]:hover {{ background: {t.accent_hover}; }}
    QPushButton[kind="primary"]:pressed {{ background: {t.focus}; }}
    QPushButton[kind="primary"]:focus {{ border: 2px solid {t.text}; }}
    QPushButton[kind="primary"]:disabled {{ background: {t.surface}; color: {t.text_secondary}; border: 1px dashed {t.border_strong}; }}
    QPushButton[kind="link"] {{ background: transparent; border: 1px solid transparent; color: {t.accent};
        padding: {px(2)} {px(4)}; min-height: 0; text-decoration: underline; }}
    QPushButton[kind="link"]:hover {{ color: {t.accent_hover}; }}
    QPushButton[kind="link"]:focus {{ border: 2px solid {t.focus}; padding: {px(1)} {px(3)}; }}

    /* ---- caixas de seleção ---- */
    QCheckBox, QRadioButton {{ spacing: {px(8)}; padding: {px(3)} {px(4)}; border: 2px solid transparent; border-radius: {px(6)}; }}
    QCheckBox:focus, QRadioButton:focus {{ border: 2px solid {t.focus}; }}
    QCheckBox:hover, QRadioButton:hover {{ background: {t.hover}; }}
    QCheckBox:disabled, QRadioButton:disabled {{ color: {t.text_secondary}; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: {px(16)}; height: {px(16)}; }}

    /* ---- controles deslizantes ---- */
    QSlider {{ min-height: {px(32)}; }}
    QSlider::groove:horizontal {{ height: {px(4)}; background: {t.groove}; border-radius: {px(2)}; }}
    QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: {px(2)}; }}
    QSlider[track="temperature"]::groove:horizontal {{
        height: {px(6)}; border-radius: {px(3)};
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E9984F, stop:0.55 #E9E4DA, stop:1 #7FA9EE);
    }}
    QSlider[track="temperature"]::sub-page:horizontal {{ background: transparent; }}
    QSlider::handle:horizontal {{
        background: #F4F6F8; border: 1px solid {t.bg};
        width: {px(18)}; height: {px(18)}; margin: -{px(8)} 0; border-radius: {px(9)};
    }}
    QSlider[track="temperature"]::handle:horizontal {{ margin: -{px(7)} 0; }}
    QSlider::handle:horizontal:hover {{ background: #FFFFFF; border: 1px solid {t.accent}; }}
    QSlider::handle:horizontal:focus {{ background: {t.focus}; border: 3px solid #F4F6F8; }}
    QSlider::sub-page:horizontal:disabled {{ background: {t.border_strong}; }}
    QSlider::handle:horizontal:disabled {{ background: {t.border_strong}; border: 1px solid {t.bg}; }}

    /* ---- campos ---- */
    QSpinBox, QComboBox, QLineEdit {{
        background: {t.raised}; color: {t.text}; border: 1px solid {t.border_strong}; border-radius: {px(6)};
        padding: {px(4)} {px(8)}; min-height: {px(22)};
    }}
    QSpinBox {{ font-weight: 600; padding-right: {px(10)}; }}
    QSpinBox::up-button, QSpinBox::down-button {{ width: 0px; border: none; }}
    QSpinBox:hover, QComboBox:hover, QLineEdit:hover {{ background: {t.hover}; }}
    QSpinBox:focus, QComboBox:focus, QLineEdit:focus {{ border: 2px solid {t.focus}; }}
    QSpinBox:disabled, QComboBox:disabled {{ color: {t.text_secondary}; background: {t.surface}; border-style: dashed; }}
    QComboBox::drop-down {{ border: none; width: {px(22)}; }}
    QComboBox QAbstractItemView {{ background: {t.raised}; border: 1px solid {t.border_strong};
        selection-background-color: {t.accent}; selection-color: {t.accent_text}; outline: none; }}

    /* ---- menus, dicas, barra de status, rolagem ---- */
    QMenuBar {{ background: {t.bg}; padding: {px(2)}; }}
    QMenuBar::item {{ padding: {px(4)} {px(10)}; border-radius: {px(6)}; }}
    QMenuBar::item:selected {{ background: {t.hover}; }}
    QMenu {{ background: {t.raised}; border: 1px solid {t.border_strong}; border-radius: {px(8)}; padding: {px(4)}; }}
    QMenu::item {{ padding: {px(6)} {px(24)} {px(6)} {px(12)}; border-radius: {px(5)}; }}
    QMenu::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
    QMenu::item:disabled {{ color: {t.text_secondary}; }}
    QMenu::separator {{ height: 1px; background: {t.border}; margin: {px(4)} {px(8)}; }}
    QToolTip {{ background: {t.raised}; color: {t.text}; border: 1px solid {t.border_strong}; padding: {px(5)}; }}
    QStatusBar {{ background: {t.surface}; color: {t.text_secondary}; }}
    QStatusBar QLabel {{ color: {t.text_secondary}; }}
    QScrollBar:vertical {{ background: transparent; width: {px(12)}; margin: {px(2)}; }}
    QScrollBar::handle:vertical {{ background: {t.border_strong}; border-radius: {px(4)}; min-height: {px(32)}; }}
    QScrollBar::handle:vertical:hover {{ background: {t.text_secondary}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    """
