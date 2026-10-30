"""Atualizações na interface: consentimento, aviso de nova versão e instalação.

* A verificação automática é opt‑in: na primeira execução um aviso pergunta.
* Encontrar uma versão nova só mostra um aviso; baixar e instalar exige clique.
* Fora do executável instalado no Windows, o app apenas abre a página da release.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from lume import APP_NAME, __version__
from lume.core import updates
from lume.ui.widgets import Banner, button

STARTUP_DELAY_MS = 8000


def can_self_install() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


class Updater(QObject):
    checked = Signal(object, bool)  # Release | UpdateError, manual?
    progressed = Signal(int, int)
    downloaded = Signal(object)  # Path | UpdateError

    def __init__(self, window, banner: Banner, *, fetch=updates.fetch_latest, download=updates.download,
                 launch=subprocess.Popen):
        super().__init__(window)
        self.window = window
        self.banner = banner
        self.prefs = window.prefs
        self._fetch = fetch
        self._download = download
        self._launch = launch
        self._busy = False
        self._cancel = False
        self.latest: updates.Release | None = None
        self.checked.connect(self._on_checked)
        self.progressed.connect(self._on_progress)
        self.downloaded.connect(self._on_downloaded)
        self.timer = QTimer(self)
        self.timer.setInterval(60 * 60 * 1000)  # confere de hora em hora se já passou 1 dia
        self.timer.timeout.connect(self._maybe_check)

    # ------------------------------------------------------------ consentimento
    def start(self) -> None:
        if self.prefs.auto_update is None:
            QTimer.singleShot(STARTUP_DELAY_MS, self._ask_consent)
        elif self.prefs.auto_update:
            QTimer.singleShot(STARTUP_DELAY_MS, self._maybe_check)
        self.timer.start()

    def _ask_consent(self) -> None:
        if self.prefs.auto_update is not None or self.banner.isVisible():
            return
        yes = button("Sim, verificar", "primary")
        yes.clicked.connect(lambda: self.set_auto(True, check_now=True))
        no = button("Agora não")
        no.clicked.connect(lambda: self.set_auto(False))
        self.banner.show_message(
            "info",
            f"Deseja que o {APP_NAME} verifique novas versões uma vez por dia? Ele só consulta a página de "
            "releases no GitHub e nunca instala nada sem sua confirmação. Você pode mudar isso em Ajustes.",
            [yes, no],
        )

    def set_auto(self, on: bool, *, check_now: bool = False) -> None:
        self.prefs.auto_update = on
        self.window._save_prefs()
        self.window.sync_update_action()
        self.banner.hide()
        if on and check_now:
            self.check(manual=False)

    # ------------------------------------------------------------ verificação
    def _maybe_check(self) -> None:
        if self.prefs.auto_update and time.time() - self.prefs.last_update_check >= updates.CHECK_INTERVAL_S:
            self.check(manual=False)

    def check(self, *, manual: bool) -> None:
        if self._busy:
            return
        self._busy = True
        if manual:
            self.window.statusBar().showMessage("Procurando atualizações…")

        def work():
            try:
                result = self._fetch()
            except updates.UpdateError as exc:
                result = exc
            self.checked.emit(result, manual)

        threading.Thread(target=work, name="lume-update-check", daemon=True).start()

    def _on_checked(self, result, manual: bool) -> None:
        self._busy = False
        if isinstance(result, updates.UpdateError):
            if manual:
                self.window.statusBar().showMessage(f"✕ {result}", 8000)
            return  # verificação automática falha em silêncio (ex.: sem internet)
        self.prefs.last_update_check = time.time()
        self.window._save_prefs()
        if not updates.is_newer(result.version):
            if manual:
                self.window.statusBar().showMessage(f"✓ Você já está na versão mais recente ({__version__}).", 6000)
            return
        if not manual and result.version == self.prefs.skipped_version:
            return
        self.latest = result
        self._offer(result)

    # ------------------------------------------------------------ oferta
    def _offer(self, release: updates.Release) -> None:
        notes = button("Ver novidades")
        notes.clicked.connect(lambda: self.show_notes(release))
        later = button("Depois")
        later.clicked.connect(self.banner.hide)
        skip = button("Pular esta versão")
        skip.clicked.connect(lambda: self._skip(release))
        if can_self_install() and release.asset_url:
            go = button("Atualizar agora", "primary")
            go.clicked.connect(lambda: self.confirm_install(release))
            text = f"Nova versão {release.version} disponível (você usa a {__version__})."
        else:
            go = button("Abrir página da versão", "primary")
            go.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(release.page_url)))
            text = (f"Nova versão {release.version} disponível (você usa a {__version__}). "
                    "Baixe o instalador na página da versão.")
        self.banner.show_message("info", text, [go, notes, later, skip])

    def _skip(self, release: updates.Release) -> None:
        self.prefs.skipped_version = release.version
        self.window._save_prefs()
        self.banner.hide()

    def show_notes(self, release: updates.Release) -> None:
        box = QMessageBox(self.window)
        box.setWindowTitle(f"Novidades da versão {release.version}")
        box.setText(f"{APP_NAME} {release.version}")
        box.setInformativeText(release.notes or "Esta versão não tem notas publicadas.")
        box.exec()

    def confirm_install(self, release: updates.Release) -> None:
        answer = QMessageBox.question(
            self.window,
            "Atualizar o Lume",
            f"Baixar e instalar a versão {release.version}?\n\n"
            "O Lume vai fechar (as cores voltam ao original), instalar a nova versão e abrir de novo. "
            "Seus perfis e preferências são mantidos.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_download(release)

    # ------------------------------------------------------------ download e instalação
    def _start_download(self, release: updates.Release) -> None:
        self._cancel = False
        cancel = button("Cancelar")
        cancel.clicked.connect(self._request_cancel)
        self.banner.show_message("info", f"Baixando a versão {release.version}…", [cancel])
        dest = Path(tempfile.gettempdir()) / "lume-update"

        def work():
            try:
                result = self._download(release, dest, self.progressed.emit, cancelled=lambda: self._cancel)
            except updates.UpdateError as exc:
                result = exc
            self.downloaded.emit(result)

        threading.Thread(target=work, name="lume-update-download", daemon=True).start()

    def _request_cancel(self) -> None:
        self._cancel = True

    def _on_progress(self, done: int, total: int) -> None:
        if total:
            pct = round(done * 100 / total)
            self.banner.text.setText(f"ⓘ Baixando atualização… {pct} % ({done // 1_048_576} de {total // 1_048_576} MB)")

    def _on_downloaded(self, result) -> None:
        if isinstance(result, updates.UpdateError):
            retry = button("Tentar de novo")
            retry.clicked.connect(lambda: self.latest and self._start_download(self.latest))
            self.banner.show_message("error", str(result), [retry] if self.latest else [])
            return
        self.banner.show_message("info", "Download verificado. Fechando o Lume para instalar…")
        try:
            self._launch(updates.installer_command(result), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            self.banner.show_message("error", f"Não foi possível iniciar o instalador: {exc}")
            return
        self.window.quit_app()
