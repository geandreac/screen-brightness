"""Janela principal.

Regras de produto aplicadas aqui:
* brilho, temperatura e filtro são independentes;
* filtros nunca são aplicados à tela sem um clique explícito e, ao ativar,
  revertem sozinhos se a pessoa não confirmar (a tela pode ficar difícil de ler);
* recurso indisponível aparece desativado, com motivo e alternativa;
* todo estado tem texto, não só cor.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QRadioButton,
    QScrollArea,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from lume import APP_NAME, __version__
from lume.core.color import FILTERS, channel_gains, filter_matrix, temperature_label
from lume.core.controller import Controller
from lume.core.engine import ApplyResult
from lume.core.models import (
    MAX_K,
    MIN_K,
    MIN_SOFT_DIM,
    NEUTRAL_K,
    Adjustments,
    Capabilities,
    FeatureStatus,
)
from lume.core.profiles import ProfileError, Store
from lume.ui.widgets import Banner, Card, ValueSlider, app_icon, button, divider, label, unavailable

REVERT_SECONDS = 15
FEATURE_NAMES = {"brightness": "o brilho", "color": "a cor", "filter": "o filtro"}


def filter_key(adj: Adjustments):
    return (adj.filter_id, adj.filter_strength) if adj.filter_active else None


def unavailable_text(status: FeatureStatus) -> str:
    return " ".join(part for part in (status.reason, status.hint) if part)


class MainWindow(QMainWindow):
    resultReady = Signal(object)
    probeDone = Signal(object)
    scaleChanged = Signal(int)

    def __init__(self, controller: Controller, store: Store, *, reduced_motion: bool = False):
        super().__init__()
        self.controller = controller
        self.store = store
        self.prefs = store.preferences
        if reduced_motion:
            self.prefs.transitions = False
        self.caps: Capabilities | None = None
        self.pending = Adjustments()
        self.filter_choice = next(iter(FILTERS))
        self.brightness_sliders: dict[str, ValueSlider] = {}
        self._confirm_previous: Adjustments | None = None
        self._confirm_left = 0
        self._undo_state: Adjustments | None = None
        self._quitting = False
        self._shut_down = False
        self._ready = False  # vira True quando todas as seções existem

        controller.on_result = self.resultReady.emit
        self.resultReady.connect(self._on_result)
        self.probeDone.connect(self._on_probed)

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(380, 460)
        self.resize(560, 760)

        self._confirm_timer = QTimer(self)
        self._confirm_timer.setInterval(1000)
        self._confirm_timer.timeout.connect(self._tick_confirm)
        self._undo_timer = QTimer(self)
        self._undo_timer.setSingleShot(True)
        self._undo_timer.timeout.connect(lambda: self.message_banner.hide())

        self._build_menu()
        self._build_shell()
        self._build_tray()
        self._build_shortcuts()
        self._start_probe()

    # ------------------------------------------------------------ estrutura
    def _build_menu(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&Arquivo")
        self.act_hide = QAction("Fechar janela", self, shortcut=QKeySequence.StandardKey.Close)
        self.act_hide.triggered.connect(self.close)
        self.act_quit = QAction("Sair e restaurar cores", self, shortcut=QKeySequence("Ctrl+Q"))
        self.act_quit.triggered.connect(self.quit_app)
        file_menu.addAction(self.act_hide)
        file_menu.addAction(self.act_quit)

        adjust = bar.addMenu("A&justes")
        self.act_restore = QAction("Restaurar originais", self, shortcut=QKeySequence("Ctrl+R"))
        self.act_restore.triggered.connect(self.restore_original)
        self.act_compare = QAction("Mostrar cores originais", self, checkable=True, shortcut=QKeySequence("Ctrl+Shift+O"))
        self.act_compare.setStatusTip("Mostra temporariamente as cores sem ajustes, sem perder suas escolhas.")
        self.act_compare.toggled.connect(self.set_comparing)
        self.act_apply = QAction("Aplicar alterações", self, shortcut=QKeySequence("Ctrl+Return"))
        self.act_apply.triggered.connect(self.apply_pending)
        self.act_transitions = QAction("Transições suaves", self, checkable=True)
        self.act_transitions.setChecked(self.prefs.transitions)
        self.act_transitions.toggled.connect(self._set_transitions)
        self.act_min_tray = QAction("Minimizar para a área de notificação", self, checkable=True)
        self.act_min_tray.setChecked(self.prefs.minimize_to_tray)
        self.act_min_tray.toggled.connect(lambda on: self._set_pref("minimize_to_tray", on))
        self.act_tray = QAction("Fechar a janela mantém o app na área de notificação", self, checkable=True)
        self.act_tray.setChecked(self.prefs.close_to_tray)
        self.act_tray.toggled.connect(lambda on: self._set_pref("close_to_tray", on))
        for act in (self.act_restore, self.act_compare, self.act_apply):
            adjust.addAction(act)
        adjust.addSeparator()
        adjust.addAction(self.act_transitions)
        adjust.addAction(self.act_min_tray)
        adjust.addAction(self.act_tray)
        from lume.platform import autostart

        if autostart.supported():
            self.act_autostart = QAction("Iniciar com o Windows (na área de notificação)", self, checkable=True)
            self.act_autostart.setChecked(autostart.is_enabled())
            self.act_autostart.toggled.connect(self._set_autostart)
            adjust.addAction(self.act_autostart)

        view = bar.addMenu("&Exibir")
        bigger = QAction("Aumentar texto", self, shortcut=QKeySequence.StandardKey.ZoomIn)
        bigger.triggered.connect(lambda: self.set_scale(self.prefs.ui_scale + 10))
        smaller = QAction("Diminuir texto", self, shortcut=QKeySequence.StandardKey.ZoomOut)
        smaller.triggered.connect(lambda: self.set_scale(self.prefs.ui_scale - 10))
        reset = QAction("Tamanho padrão do texto", self, shortcut=QKeySequence("Ctrl+0"))
        reset.triggered.connect(lambda: self.set_scale(100))
        for act in (bigger, smaller, reset):
            view.addAction(act)

        help_menu = bar.addMenu("A&juda")
        compat = QAction("Compatibilidade desta tela…", self)
        compat.triggered.connect(self.show_compatibility)
        about = QAction(f"Sobre o {APP_NAME}", self)
        about.triggered.connect(self.show_about)
        help_menu.addAction(compat)
        help_menu.addAction(about)

    def _build_shell(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("content")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(20, 16, 20, 24)
        self.content_layout.setSpacing(12)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll, 1)

        # Cabeçalho: finalidade + estado geral
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = label(APP_NAME, "title")
        titles.addWidget(self.title_label)
        titles.addWidget(label("Brilho e cor da tela, do seu jeito.", "subtitle", wrap=True))
        head.addLayout(titles, 1)
        state_col = QVBoxLayout()
        state_col.setSpacing(2)
        from lume.ui.widgets import StatusPill

        self.state_pill = StatusPill()
        self.state_pill.set_state("off", "Detectando…")
        self.compat_link = button("Compatibilidade", "link", tip="Ver o que este sistema e cada monitor permitem")
        self.compat_link.clicked.connect(self.show_compatibility)
        state_col.addWidget(self.state_pill, 0, Qt.AlignmentFlag.AlignRight)
        state_col.addWidget(self.compat_link, 0, Qt.AlignmentFlag.AlignRight)
        state_col.addStretch(1)
        head.addLayout(state_col)
        self.content_layout.addLayout(head)

        # Avisos persistentes e mensagens
        self.demo_banner = Banner()
        self.filter_banner = Banner()
        self.confirm_banner = Banner()
        self.message_banner = Banner()
        for b in (self.demo_banner, self.filter_banner, self.confirm_banner, self.message_banner):
            self.content_layout.addWidget(b)

        self.loading_panel = QFrame()
        self.loading_panel.setObjectName("loading")
        loading_lay = QVBoxLayout(self.loading_panel)
        loading_lay.setContentsMargins(16, 14, 16, 14)
        self.loading = label("◌  Detectando telas e recursos disponíveis…", "help", wrap=True)
        self.loading.setAccessibleName("Detectando telas e recursos disponíveis")
        loading_lay.addWidget(self.loading)
        self.content_layout.addWidget(self.loading_panel)

        # Duas colunas independentes (cada uma com sua altura) em janelas largas.
        self.grid_host = QWidget()
        columns = QHBoxLayout(self.grid_host)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(20)
        self.col_left, self.col_right = QVBoxLayout(), QVBoxLayout()
        for col in (self.col_left, self.col_right):
            col.setSpacing(20)
            columns.addLayout(col, 1)
        self.content_layout.addWidget(self.grid_host)
        self.content_layout.addStretch(1)

        outer.addWidget(self._build_footer())
        self.setCentralWidget(root)
        self.statusBar().setSizeGripEnabled(True)

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("footer")
        lay = QGridLayout(footer)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(6)

        self.immediate = QCheckBox("Aplicar imediatamente")
        self.immediate.setChecked(self.prefs.apply_immediately)
        self.immediate.setToolTip(
            "Ligado: brilho e temperatura mudam enquanto você ajusta. "
            "Desligado: veja na prévia e clique em Aplicar. Filtros sempre pedem confirmação."
        )
        self.immediate.toggled.connect(self._set_immediate)
        self.pending_label = label("", "help")

        self.compare_btn = button(
            "Comparar com original",
            tip="Segure para ver as cores originais. Para alternar pelo teclado use Ctrl+Shift+O.",
        )
        self.compare_btn.pressed.connect(lambda: self.set_comparing(True))
        self.compare_btn.released.connect(lambda: self.set_comparing(False))
        self.restore_btn = button("Restaurar originais", tip="Volta brilho e cores ao estado de quando o app abriu (Ctrl+R)")
        self.restore_btn.clicked.connect(self.restore_original)
        self.discard_btn = button("Descartar")
        self.discard_btn.clicked.connect(self.discard_pending)
        self.apply_btn = button("Aplicar", "primary", tip="Aplica as alterações pendentes (Ctrl+Enter)")
        self.apply_btn.clicked.connect(self.apply_pending)

        left = QHBoxLayout()
        left.addWidget(self.immediate)
        left.addSpacing(8)
        left.addWidget(self.pending_label, 1)
        right = QHBoxLayout()
        right.setSpacing(8)
        right.addWidget(self.compare_btn)
        right.addWidget(self.restore_btn)
        right.addSpacing(8)
        right.addWidget(self.discard_btn)
        right.addWidget(self.apply_btn)
        self._footer_grid, self._footer_left, self._footer_right = lay, left, right
        self._footer_wide = None
        self._flow_footer()
        for w in (self.compare_btn, self.restore_btn, self.discard_btn, self.apply_btn, self.immediate):
            w.setEnabled(False)
        self.discard_btn.hide()
        self.apply_btn.hide()
        return footer

    def _build_tray(self) -> None:
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            for act in (self.act_tray, self.act_min_tray):
                act.setEnabled(False)
            self.act_min_tray.setText("Minimizar para a área de notificação (indisponível neste sistema)")
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        menu = QMenu(self)
        show = menu.addAction(f"Abrir {APP_NAME}")
        show.triggered.connect(self.show_window)
        menu.addSeparator()
        menu.addAction(self.act_compare)
        menu.addAction(self.act_restore)
        menu.addSeparator()
        menu.addAction(self.act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.setToolTip(APP_NAME)
        self.tray.show()

    def _build_shortcuts(self) -> None:
        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc.activated.connect(lambda: self.revert_filter() if self._confirm_previous else None)

    # ------------------------------------------------------------ detecção
    def _start_probe(self) -> None:
        def work():
            try:
                self.probeDone.emit(self.controller.initialize())
            except Exception as exc:  # noqa: BLE001 — mostrado na tela, com tentativa nova
                self.probeDone.emit(exc)

        threading.Thread(target=work, name="lume-probe", daemon=True).start()

    def _on_probed(self, result) -> None:
        if isinstance(result, Exception):
            retry = button("Tentar novamente")
            retry.clicked.connect(lambda: (self.message_banner.hide(), self._start_probe()))
            self.loading.setText("✕  Não foi possível detectar as telas.")
            self.message_banner.show_message("error", f"Falha ao consultar o sistema: {result}", [retry])
            return
        self.caps = result
        self.pending = self.controller.original
        self.loading_panel.hide()
        self._build_sections()
        for w in (self.compare_btn, self.restore_btn, self.immediate):
            w.setEnabled(True)
        if result.simulated:
            self.demo_banner.show_message(
                "warn", "Modo demonstração: nenhuma alteração real é feita na tela. Os valores são simulados."
            )
        if self.store.load_warning:
            self.message_banner.show_message("warn", self.store.load_warning)
        self.refresh()

    # ------------------------------------------------------------ seções
    def _build_sections(self) -> None:
        caps = self.caps
        assert caps is not None
        self.brightness_card = self._brightness_card(caps)
        self.temperature_card = self._temperature_card(caps)
        self.filter_card = self._filter_card(caps)
        self.preview_card = self._preview_card()
        self.profiles_card = self._profiles_card()
        self._cards_left = [self.brightness_card, self.temperature_card, self.profiles_card]
        self._cards_right = [self.preview_card, self.filter_card]
        self._two_columns = None
        self._relayout()
        self._ready = True
        QTimer.singleShot(0, self._fit_min_width)
        # Ordem de tabulação segue a ordem visual de leitura.
        QWidget.setTabOrder(self.compat_link, self.brightness_card)

    def _brightness_card(self, caps: Capabilities) -> Card:
        card = Card("Brilho", "Brilho de hardware altera a luz do monitor. Nada muda sozinho.")
        any_hw = False
        for display in caps.displays:
            if display.brightness.available:
                any_hw = True
                value = self.controller.original.brightness.get(display.id, 100)
                slider = ValueSlider(
                    display.name, display.brightness_min, 100, value,
                    left_caption="Mais escuro", right_caption="Mais claro",
                    describe=lambda v, m=display.brightness.method: m,
                )
                slider.valueChanged.connect(lambda v, drag, d=display.id: self._on_brightness(d, v, drag))
                self.brightness_sliders[display.id] = slider
                card.body.addWidget(slider)
            else:
                row = QVBoxLayout()
                row.setSpacing(2)
                row.addWidget(label(display.name, "label-strong"))
                row.setSpacing(6)
                row.addWidget(unavailable("Brilho de hardware indisponível. " + unavailable_text(display.brightness)))
                card.body.addLayout(row)
        if not caps.displays:
            card.body.addWidget(unavailable("Nenhuma tela foi identificada pelo sistema."))

        card.body.addWidget(divider())
        self.dim_slider = ValueSlider(
            "Escurecimento por software", MIN_SOFT_DIM, 100, 100,
            left_caption=f"{MIN_SOFT_DIM} % (mais escuro)", right_caption="100 % (sem escurecer)",
            help_text="Reduz a intensidade das cores na saída de vídeo, em todas as telas. "
            "Não diminui a luz de fundo; útil abaixo do mínimo do monitor ou quando não há controle de hardware.",
        )
        self.dim_slider.valueChanged.connect(lambda v, drag: self._on_color("soft_dim", v, drag))
        card.body.addWidget(self.dim_slider)
        if not caps.soft_dim.available:
            self.dim_slider.setEnabled(False)
            card.body.addWidget(unavailable("Indisponível: " + unavailable_text(caps.soft_dim)))
        state = (
            ("ok", "Disponível") if any_hw and caps.soft_dim.available
            else ("warn", "Parcial") if any_hw or caps.soft_dim.available
            else ("off", "Indisponível")
        )
        card.pill.set_state(*state)
        return card

    def _temperature_card(self, caps: Capabilities) -> Card:
        card = Card(
            "Temperatura de cor",
            "Do tom mais quente (amarelado) ao mais frio (azulado). 6500 K é o neutro. Não muda o brilho de hardware.",
        )
        self.temp_slider = ValueSlider(
            "Temperatura", MIN_K, MAX_K, NEUTRAL_K, unit="K", step=100, page=500,
            left_caption="Mais quente", right_caption="Mais fria",
            describe=temperature_label, track="temperature",
        )
        self.temp_slider.valueChanged.connect(lambda v, drag: self._on_color("temperature", v, drag))
        card.body.addWidget(self.temp_slider)
        row = QHBoxLayout()
        self.neutral_btn = button("Voltar ao neutro (6500 K)")
        self.neutral_btn.clicked.connect(lambda: self._on_color("temperature", NEUTRAL_K, False, sync=True))
        row.addWidget(self.neutral_btn)
        row.addStretch(1)
        card.body.addLayout(row)
        if not caps.temperature.available:
            self.temp_slider.setEnabled(False)
            self.neutral_btn.setEnabled(False)
            card.body.addWidget(unavailable("Indisponível: " + unavailable_text(caps.temperature)))
            card.pill.set_state("off", "Indisponível")
        return card

    def _filter_card(self, caps: Capabilities) -> Card:
        card = Card(
            "Filtros de cor (experimental)",
            "Opcionais e desligados por padrão. Não são tratamento nem correção médica: o efeito varia "
            "de pessoa para pessoa e entre monitores. Teste na prévia antes de aplicar.",
        )
        self.filter_toggle = QCheckBox("Usar um filtro de cor")
        self.filter_toggle.toggled.connect(self._on_filter_toggle)
        card.body.addWidget(self.filter_toggle)

        self.filter_group = QButtonGroup(self)
        self.filter_radios: dict[str, QRadioButton] = {}
        options = QVBoxLayout()
        options.setSpacing(2)
        options.setContentsMargins(24, 0, 0, 0)
        for f in FILTERS.values():
            radio = QRadioButton(f.name)
            radio.setAccessibleDescription(f.description)
            radio.setToolTip(f.description)
            self.filter_group.addButton(radio)
            self.filter_radios[f.id] = radio
            radio.toggled.connect(lambda on, fid=f.id: on and self._on_filter_choice(fid))
            options.addWidget(radio)
            hint = label(f.description, "help", wrap=True)
            hint.setContentsMargins(26, 0, 0, 4)
            options.addWidget(hint)
        self.filter_radios[self.filter_choice].setChecked(True)
        card.body.addLayout(options)

        self.strength_slider = ValueSlider("Intensidade", 10, 100, 100, left_caption="Sutil", right_caption="Máxima")
        self.strength_slider.valueChanged.connect(lambda v, drag: self._on_filter_strength(v))
        card.body.addWidget(self.strength_slider)

        actions = QHBoxLayout()
        self.filter_apply_btn = button("Aplicar filtro à tela", "primary")
        self.filter_apply_btn.clicked.connect(self.apply_filter)
        self.filter_off_btn = button("Desativar filtro")
        self.filter_off_btn.clicked.connect(self.disable_filter)
        actions.addWidget(self.filter_apply_btn)
        actions.addWidget(self.filter_off_btn)
        actions.addStretch(1)
        card.body.addLayout(actions)
        if not caps.filters.available:
            self.filter_apply_btn.hide()
            self.filter_off_btn.hide()
            card.body.addWidget(unavailable("Só na prévia neste sistema. " + unavailable_text(caps.filters)))
        self._set_filter_controls_enabled(False)
        return card

    def _preview_card(self) -> Card:
        from lume.ui.preview import PreviewWidget

        card = Card("Prévia", "")
        self.preview = PreviewWidget()
        card.body.addWidget(self.preview)
        self.preview_note = label("", "help", wrap=True)
        card.body.addWidget(self.preview_note)
        return card

    def _profiles_card(self) -> Card:
        card = Card(
            "Perfis",
            "Guarde combinações de ajustes (por exemplo “Dia” ou “Noite”) para trocar com um clique. "
            "Nenhum perfil é aplicado automaticamente.",
        )
        self.profile_combo = QComboBox()
        self.profile_combo.setAccessibleName("Perfis salvos")
        self.profile_empty = label("Nenhum perfil salvo ainda.", "help", wrap=True)
        row = QHBoxLayout()
        row.addWidget(self.profile_combo, 1)
        self.profile_apply = button("Aplicar perfil")
        self.profile_apply.clicked.connect(self.apply_profile)
        self.profile_delete = button("Excluir")
        self.profile_delete.clicked.connect(self.delete_profile)
        row.addWidget(self.profile_apply)
        row.addWidget(self.profile_delete)
        card.body.addWidget(self.profile_empty)
        card.body.addLayout(row)
        save_row = QHBoxLayout()
        save = button("Salvar ajustes atuais como perfil…")
        save.clicked.connect(self.save_profile)
        save_row.addWidget(save)
        save_row.addStretch(1)
        card.body.addLayout(save_row)
        self._reload_profiles()
        return card

    def _relayout(self) -> None:
        if not hasattr(self, "_cards_left"):
            return
        two = self.width() >= 980
        if two == self._two_columns:
            return
        self._two_columns = two
        for col in (self.col_left, self.col_right):
            while col.count():
                col.takeAt(0)
        if two:
            left, right = self._cards_left, self._cards_right
        else:
            left = [self.brightness_card, self.temperature_card, self.preview_card, self.filter_card, self.profiles_card]
            right = []
        for card in left:
            self.col_left.addWidget(card)
        for card in right:
            self.col_right.addWidget(card)
        self.col_left.addStretch(1)
        self.col_right.addStretch(1)
        self.grid_host.layout().setStretch(1, 1 if two else 0)

    def _fit_min_width(self) -> None:
        """A janela nunca fica mais estreita que o conteúdo (importante com texto ampliado)."""
        bar = self.scroll.verticalScrollBar().sizeHint().width()
        single = self._two_columns is False
        need = self.content.minimumSizeHint().width() if single else 0
        need = max(need, self.centralWidget().layout().itemAt(1).widget().minimumSizeHint().width())
        self.setMinimumWidth(max(380, need + bar + 4))

    def _flow_footer(self) -> None:
        """Uma linha em janelas largas; duas quando estreita. Só muda a posição."""
        wide = self.width() >= 820
        if wide == self._footer_wide:
            return
        self._footer_wide = wide
        grid = self._footer_grid
        grid.removeItem(self._footer_left)
        grid.removeItem(self._footer_right)
        if wide:
            grid.addLayout(self._footer_left, 0, 0)
            grid.addLayout(self._footer_right, 0, 1, Qt.AlignmentFlag.AlignRight)
        else:
            grid.addLayout(self._footer_left, 0, 0)
            grid.addLayout(self._footer_right, 1, 0, Qt.AlignmentFlag.AlignLeft)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()
        self._flow_footer()

    # ------------------------------------------------------------ alterações
    @property
    def transitions(self) -> bool:
        return self.prefs.transitions

    def _screen_target(self, include_filter: bool) -> Adjustments:
        if include_filter:
            return self.pending
        t = self.controller.target
        return self.pending.with_(filter_id=t.filter_id, filter_strength=t.filter_strength)

    def _send(self, target: Adjustments, *, animate: bool) -> None:
        self.statusBar().showMessage("Aplicando…")
        self.controller.request(target, animate=animate)

    def _on_brightness(self, display_id: str, value: int, dragging: bool) -> None:
        self.pending = self.pending.with_brightness(display_id, value)
        self._after_change(dragging)

    def _on_color(self, field: str, value: int, dragging: bool, *, sync: bool = False) -> None:
        self.pending = self.pending.with_(**{field: value})
        if sync:
            (self.temp_slider if field == "temperature" else self.dim_slider).set_value(value)
        self._after_change(dragging)

    def _after_change(self, dragging: bool) -> None:
        if self.prefs.apply_immediately:
            self._send(self._screen_target(False), animate=self.transitions and not dragging)
        self.refresh()

    def _set_filter_controls_enabled(self, on: bool) -> None:
        for radio in self.filter_radios.values():
            radio.setEnabled(on)
        self.strength_slider.setEnabled(on)

    def _on_filter_toggle(self, on: bool) -> None:
        self._set_filter_controls_enabled(on)
        self.pending = self.pending.with_(
            filter_id=self.filter_choice if on else None, filter_strength=self.strength_slider.value()
        )
        self.refresh()

    def _on_filter_choice(self, filter_id: str) -> None:
        self.filter_choice = filter_id
        if self.filter_toggle.isChecked():
            self.pending = self.pending.with_(filter_id=filter_id)
        self.refresh()

    def _on_filter_strength(self, value: int) -> None:
        self.pending = self.pending.with_(filter_strength=value)
        self.refresh()

    # ------------------------------------------------------------ ações
    def apply_filter(self) -> None:
        target = self.controller.target.with_(
            filter_id=self.pending.filter_id, filter_strength=self.pending.filter_strength
        )
        self._apply_with_confirmation(target)

    def disable_filter(self) -> None:
        self.filter_toggle.setChecked(False)
        target = self.controller.target.with_(filter_id=None)
        self._cancel_confirm()
        self._send(target, animate=self.transitions)
        self.refresh()

    def apply_pending(self) -> None:
        if self.caps is None:
            return
        target = self._screen_target(include_filter=bool(self.caps.filters.available))
        self._apply_with_confirmation(target)

    def discard_pending(self) -> None:
        self._load_into_ui(self.controller.target)
        self.refresh()

    def _apply_with_confirmation(self, target: Adjustments) -> None:
        previous = self.controller.target
        new_key, old_key = filter_key(target), filter_key(previous)
        risky = new_key is not None and (old_key is None or new_key[0] != old_key[0])
        self._send(target, animate=self.transitions)
        if risky:
            self._confirm_previous = previous if self._confirm_previous is None else self._confirm_previous
            self._confirm_left = REVERT_SECONDS
            self._show_confirm()
            self._confirm_timer.start()
        self.refresh()

    def _show_confirm(self) -> None:
        keep = button("Manter", "primary")
        keep.clicked.connect(self._cancel_confirm)
        revert = button("Reverter agora")
        revert.clicked.connect(self.revert_filter)
        self.confirm_banner.show_message(
            "warn",
            f"Filtro aplicado à tela. Se as cores ficaram difíceis de ler, ele será desfeito em "
            f"{self._confirm_left} s (ou pressione Esc).",
            [keep, revert],
        )

    def _tick_confirm(self) -> None:
        self._confirm_left -= 1
        if self._confirm_left <= 0:
            self.revert_filter()
            self.message_banner.show_message("info", "O filtro foi revertido porque não houve confirmação.")
            return
        self.confirm_banner.text.setText(
            f"⚠ Filtro aplicado à tela. Se as cores ficaram difíceis de ler, ele será desfeito em "
            f"{self._confirm_left} s (ou pressione Esc)."
        )

    def _cancel_confirm(self) -> None:
        self._confirm_timer.stop()
        self._confirm_previous = None
        self.confirm_banner.hide()

    def revert_filter(self) -> None:
        previous = self._confirm_previous
        self._cancel_confirm()
        if previous is None:
            return
        target = self.controller.target.with_(filter_id=previous.filter_id, filter_strength=previous.filter_strength)
        self._send(target, animate=False)
        self._load_filter_into_ui(previous)
        self.refresh()

    def restore_original(self) -> None:
        if self.caps is None:
            return
        self._undo_state = self.controller.target
        self._cancel_confirm()
        self.act_compare.setChecked(False)
        self.controller.restore_original(animate=self.transitions)
        self._load_into_ui(self.controller.original)
        undo = button("Desfazer")
        undo.clicked.connect(self.undo_restore)
        self.message_banner.show_message("info", "Brilho e cores voltaram ao estado de quando o app abriu.", [undo])
        self._undo_timer.start(15000)
        self.refresh()

    def undo_restore(self) -> None:
        if self._undo_state is None:
            return
        state, self._undo_state = self._undo_state, None
        self.message_banner.hide()
        self._load_into_ui(state)
        self._send(state, animate=self.transitions)
        self.refresh()

    def set_comparing(self, active: bool) -> None:
        if self.caps is None:
            return
        if self.act_compare.isChecked() != active:
            self.act_compare.blockSignals(True)
            self.act_compare.setChecked(active)
            self.act_compare.blockSignals(False)
        self.controller.compare(active)
        self.refresh()

    # ------------------------------------------------------------ perfis
    def _reload_profiles(self, select: str | None = None) -> None:
        self.profile_combo.clear()
        names = sorted(self.store.profiles, key=str.casefold)
        self.profile_combo.addItems(names)
        if select in names:
            self.profile_combo.setCurrentText(select)
        has = bool(names)
        self.profile_empty.setVisible(not has)
        for w in (self.profile_combo, self.profile_apply, self.profile_delete):
            w.setEnabled(has)

    def save_profile(self) -> None:
        suggestions = ["Dia", "Noite", "Personalizado"] + [
            n for n in sorted(self.store.profiles) if n not in ("Dia", "Noite", "Personalizado")
        ]
        name, ok = QInputDialog.getItem(
            self, "Salvar perfil", "Nome do perfil (os ajustes atuais serão guardados):", suggestions, 0, True
        )
        if not ok:
            return
        try:
            name = Store.clean_name(name)
        except ProfileError as exc:
            QMessageBox.warning(self, "Salvar perfil", str(exc))
            return
        if name in self.store.profiles:
            answer = QMessageBox.question(self, "Substituir perfil", f"Já existe um perfil “{name}”. Substituir?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self.store.save_profile(name, self.pending)
        except OSError as exc:
            self.message_banner.show_message("error", f"Não foi possível salvar o perfil: {exc}")
            return
        self._reload_profiles(select=name)
        self.statusBar().showMessage(f"✓ Perfil “{name}” salvo.", 5000)

    def apply_profile(self) -> None:
        name = self.profile_combo.currentText()
        profile = self.store.profiles.get(name)
        if profile is None or self.caps is None:
            return
        brightness = dict(self.pending.brightness)
        for display_id, value in profile.brightness.items():
            if display_id in self.brightness_sliders:
                brightness[display_id] = value
        target = profile.with_(brightness=brightness)
        notes = []
        if profile.filter_active and not self.caps.filters.available:
            notes.append("Este perfil inclui um filtro que o sistema não aplica à tela; ele aparece só na prévia.")
        if not self.caps.temperature.available and not profile.color_neutral:
            notes.append("A temperatura/escurecimento do perfil não pode ser aplicada neste sistema.")
        self._load_into_ui(target)
        screen = target if self.caps.filters.available else target.with_(filter_id=None)
        self._apply_with_confirmation(screen)
        if notes:
            self.message_banner.show_message("info", " ".join(notes))
        self.statusBar().showMessage(f"Perfil “{name}” aplicado.", 5000)

    def delete_profile(self) -> None:
        name = self.profile_combo.currentText()
        if not name:
            return
        answer = QMessageBox.question(self, "Excluir perfil", f"Excluir o perfil “{name}”? Isso não altera a tela.")
        if answer == QMessageBox.StandardButton.Yes:
            self.store.delete_profile(name)
            self._reload_profiles()

    # ------------------------------------------------------------ sincronização
    def _load_into_ui(self, adj: Adjustments) -> None:
        self.pending = adj
        for display_id, slider in self.brightness_sliders.items():
            if display_id in adj.brightness:
                slider.set_value(adj.brightness[display_id])
        self.temp_slider.set_value(adj.temperature)
        self.dim_slider.set_value(adj.soft_dim)
        self._load_filter_into_ui(adj)

    def _load_filter_into_ui(self, adj: Adjustments) -> None:
        self.pending = self.pending.with_(filter_id=adj.filter_id, filter_strength=adj.filter_strength)
        active = adj.filter_id is not None
        if adj.filter_id:
            self.filter_choice = adj.filter_id
            radio = self.filter_radios[adj.filter_id]
            radio.blockSignals(True)
            radio.setChecked(True)
            radio.blockSignals(False)
        self.filter_toggle.blockSignals(True)
        self.filter_toggle.setChecked(active)
        self.filter_toggle.blockSignals(False)
        self._set_filter_controls_enabled(active)
        self.strength_slider.set_value(max(10, adj.filter_strength))

    def _on_result(self, result: ApplyResult) -> None:
        if not result.completed:
            return
        if not result.errors:
            self.statusBar().showMessage("✓ Aplicado.", 3000)
        else:
            parts = []
            actual = result.actual
            for err in result.errors:
                what = FEATURE_NAMES.get(err.feature, err.feature)
                if err.display_id and self.caps and self.caps.display(err.display_id):
                    what += f" de “{self.caps.display(err.display_id).name}”"
                parts.append(f"Não foi possível aplicar {what}: {err.error}")
                # A interface volta ao valor que realmente está na tela.
                if err.feature == "color":
                    self.pending = self.pending.with_(temperature=actual.temperature, soft_dim=actual.soft_dim)
                    self.temp_slider.set_value(actual.temperature)
                    self.dim_slider.set_value(actual.soft_dim)
                elif err.feature == "filter":
                    self._cancel_confirm()
                    self._load_filter_into_ui(actual)
                elif err.feature == "brightness" and err.display_id in actual.brightness:
                    value = actual.brightness[err.display_id]
                    self.pending = self.pending.with_brightness(err.display_id, value)
                    self.brightness_sliders[err.display_id].set_value(value)
            self.controller.reconcile(result)
            self.statusBar().showMessage("Algumas alterações não foram aplicadas.", 5000)
            self.message_banner.show_message("error", "\n".join(parts))
        self.refresh()

    def refresh(self) -> None:
        if self.caps is None or not self._ready:
            return
        applied_target = self.controller.target
        comparing = self.controller.comparing
        filter_on_screen = filter_key(applied_target)

        # Estado geral
        if comparing:
            self.state_pill.set_state("warn", "Mostrando cores originais")
        elif filter_on_screen:
            self.state_pill.set_state("active", "Filtro de cor ativo")
        elif not applied_target.color_neutral:
            self.state_pill.set_state("active", "Ajustes de cor ativos")
        else:
            self.state_pill.set_state("off", "Cores originais")

        # Indicação persistente de filtro
        if filter_on_screen and not comparing:
            f = FILTERS[filter_on_screen[0]]
            off = button("Desativar filtro")
            off.clicked.connect(self.disable_filter)
            self.filter_banner.show_message(
                "info",
                f"Filtro ativo: {f.name}, {filter_on_screen[1]} %. As cores da tela não são as originais "
                "— use “Comparar com original” para checar trabalhos de cor.",
                [off],
            )
        else:
            self.filter_banner.hide()
        suffix = " — filtro ativo" if filter_on_screen else ""
        self.setWindowTitle(APP_NAME + suffix)
        if self.tray:
            self.tray.setToolTip(f"{APP_NAME}{suffix}")

        # Temperatura
        if self.caps.temperature.available:
            if applied_target.temperature != NEUTRAL_K:
                self.temperature_card.pill.set_state("active", f"Ativa: {applied_target.temperature} K")
            else:
                self.temperature_card.pill.set_state("off", "Neutra")
            self.neutral_btn.setEnabled(self.pending.temperature != NEUTRAL_K)

        # Filtros
        if self.caps.filters.available:
            if filter_on_screen:
                self.filter_card.pill.set_state("active", "Ativo na tela")
            else:
                self.filter_card.pill.set_state("off", "Desligado")
            want = filter_key(self.pending)
            self.filter_apply_btn.setEnabled(want is not None and want != filter_on_screen)
            self.filter_apply_btn.setText("Atualizar filtro na tela" if filter_on_screen and want else "Aplicar filtro à tela")
            self.filter_off_btn.setVisible(filter_on_screen is not None)
        else:
            self.filter_card.pill.set_state("off", "Só na prévia")

        # Prévia: mostra o que está escolhido (pendente), lado a lado com o original.
        matrix = filter_matrix(self.pending.filter_id, self.pending.filter_strength)
        self.preview.set_effect(channel_gains(self.pending.temperature, self.pending.soft_dim), matrix)
        if not applied_target.color_neutral and not comparing:
            self.preview_note.setText(
                "Os ajustes já aplicados alteram a tela inteira, inclusive esta prévia. "
                "Para comparar fielmente, use “Comparar com original”."
            )
        else:
            self.preview_note.setText("A prévia não altera a tela: experimente à vontade.")

        # Pendências
        dirty_basic = self._screen_target(False) != applied_target
        dirty_filter = self.caps.filters.available and filter_key(self.pending) != filter_on_screen
        dirty = dirty_basic or dirty_filter
        manual = not self.prefs.apply_immediately
        self.apply_btn.setVisible(manual)
        self.discard_btn.setVisible(manual)
        self.apply_btn.setEnabled(manual and dirty)
        self.discard_btn.setEnabled(manual and dirty)
        self.act_apply.setEnabled(manual and dirty)
        if manual and dirty:
            self.pending_label.setText("● Há alterações não aplicadas")
        elif dirty_filter and filter_key(self.pending) is not None:
            self.pending_label.setText("Filtro só na prévia")
        else:
            self.pending_label.setText("")

    # ------------------------------------------------------------ preferências
    def _set_immediate(self, on: bool) -> None:
        self.prefs.apply_immediately = on
        self._save_prefs()
        self.refresh()

    def _set_transitions(self, on: bool) -> None:
        self.prefs.transitions = on
        self._save_prefs()

    def _set_pref(self, name: str, on: bool) -> None:
        setattr(self.prefs, name, on)
        self._save_prefs()

    def _set_autostart(self, on: bool) -> None:
        from lume.platform import autostart

        try:
            autostart.set_enabled(on)
        except OSError as exc:
            self.act_autostart.blockSignals(True)
            self.act_autostart.setChecked(not on)
            self.act_autostart.blockSignals(False)
            self.message_banner.show_message("error", f"Não foi possível alterar a inicialização automática: {exc}")

    def set_scale(self, scale: int) -> None:
        scale = max(80, min(200, scale))
        if scale == self.prefs.ui_scale:
            return
        self.prefs.ui_scale = scale
        self._save_prefs()
        self.scaleChanged.emit(scale)
        self.statusBar().showMessage(f"Tamanho do texto: {scale} %", 3000)

    def _save_prefs(self) -> None:
        try:
            self.store.save()
        except OSError as exc:
            self.statusBar().showMessage(f"Não foi possível salvar as preferências: {exc}", 6000)

    # ------------------------------------------------------------ diálogos
    def show_compatibility(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Compatibilidade")
        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(0, 0, 0, 12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        holder.setObjectName("content")
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(20, 16, 20, 8)
        lay.setSpacing(16)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)
        if self.caps is None:
            lay.addWidget(label("Ainda detectando…", "help"))
        else:
            caps = self.caps
            lay.addWidget(label(f"Sistema: {caps.platform_label}", "title"))

            def row(target: QVBoxLayout, name: str, status: FeatureStatus) -> None:
                line = QVBoxLayout()
                line.setSpacing(2)
                line.addWidget(label(name, "label"))
                if status.available:
                    line.addWidget(label(f"✓  Disponível — {status.method}", "help", wrap=True))
                else:
                    line.addWidget(unavailable("Indisponível. " + unavailable_text(status)))
                target.addLayout(line)

            displays = Card("Brilho de hardware")
            for d in caps.displays:
                row(displays.body, d.name, d.brightness)
            lay.addWidget(displays)
            color = Card("Cor")
            row(color.body, "Temperatura de cor", caps.temperature)
            row(color.body, "Escurecimento por software", caps.soft_dim)
            row(color.body, "Filtros de cor na tela", caps.filters)
            lay.addWidget(color)
            notes = Card("Observações")
            for note in caps.notes:
                notes.body.addWidget(label("ⓘ  " + note, "help", wrap=True))
            notes.body.addWidget(label(
                "Permissões: o programa não pede privilégios de administrador. No Linux, o brilho da luz de "
                "fundo usa o systemd‑logind e monitores externos exigem acesso ao I²C (veja o README).",
                "help", wrap=True,
            ))
            lay.addWidget(notes)
        lay.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(dlg.reject)
        box.setContentsMargins(20, 0, 20, 0)
        outer.addWidget(box)
        dlg.resize(560, 560)
        dlg.exec()

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            f"Sobre o {APP_NAME}",
            f"{APP_NAME} {__version__}\n\nAjuste de brilho, temperatura de cor e filtros opcionais.\n\n"
            "Os filtros são experimentais e não substituem orientação profissional. O programa não coleta "
            "dados pessoais nem de saúde; só guarda seus perfis e preferências neste computador.",
        )

    # ------------------------------------------------------------ janela / saída
    def show_window(self) -> None:
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason) -> None:
        # Clique simples ou duplo no ícone: abre (ou esconde, se já estiver à frente).
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized() and self.isActiveWindow():
                self.hide_to_tray()
            else:
                self.show_window()

    def hide_to_tray(self) -> None:
        self.hide()
        if self.tray and not self.prefs.tray_notice_shown:
            self.prefs.tray_notice_shown = True
            self._save_prefs()
            self.tray.showMessage(
                APP_NAME,
                "O Lume continua aberto aqui na área de notificação. Clique no ícone para abrir; "
                "clique com o botão direito para restaurar as cores ou sair.",
                QSystemTrayIcon.MessageIcon.Information,
                6000,
            )

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._quitting and self.tray and self.prefs.close_to_tray:
            event.ignore()
            self.hide_to_tray()
            return
        event.accept()
        self.quit_app()

    def quit_app(self) -> None:
        self._quitting = True
        self.shutdown()
        QApplication.quit()

    def shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True
        self._confirm_timer.stop()
        # Cores e filtros voltam ao original; o brilho de hardware fica como está,
        # como acontece com o controle de brilho do próprio sistema.
        self.controller.shutdown(restore_color=True)
        if self.tray:
            self.tray.hide()
        self._save_prefs()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self.tray
            and self.prefs.minimize_to_tray
        ):
            # Sai da barra de tarefas e fica só o ícone pequeno na área de notificação.
            QTimer.singleShot(0, self.hide_to_tray)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange) and self._ready:
            QTimer.singleShot(0, self._fit_min_width)
