"""Ponto de entrada: ``python -m lume`` ou o executável gerado."""

from __future__ import annotations

import argparse
import signal
import sys

from lume import APP_ID, APP_NAME, __version__


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_ID, description=f"{APP_NAME}: brilho e cor da tela.")
    parser.add_argument("--demo", action="store_true", help="modo demonstração: não altera a tela de verdade")
    parser.add_argument(
        "--reset-colors",
        action="store_true",
        help="restaura curvas de cor lineares e sai (use se o app foi fechado à força com cores alteradas)",
    )
    parser.add_argument("--tray", action="store_true", help="inicia escondido, só com o ícone na área de notificação")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return parser.parse_args(argv)


def reset_colors() -> int:
    """Recuperação de emergência sem abrir a interface."""
    from lume.core.errors import BackendError
    from lume.platform import create_backend

    try:
        backend = create_backend()
        backend.probe()
        reset = getattr(backend, "reset_color_to_linear", None)
        if reset:
            reset()
        else:
            backend.set_color_gains((1.0, 1.0, 1.0))
            backend.set_filter(None)
        backend.close()
    except BackendError as exc:
        print(f"Não foi possível restaurar as cores: {exc}", file=sys.stderr)
        return 1
    print("Cores restauradas.")
    return 0


def _windows_mutex():
    """Mutex nomeado: o instalador (AppMutex) detecta o app aberto antes de atualizar."""
    if sys.platform != "win32":
        return None
    import ctypes

    return ctypes.windll.kernel32.CreateMutexW(None, False, "LumeAppMutex")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.reset_colors:
        return reset_colors()

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from lume.core.controller import Controller
    from lume.core.paths import config_dir
    from lume.core.profiles import Store
    from lume.platform import create_backend, high_contrast_enabled, prefers_reduced_motion
    from lume.ui import theme
    from lume.ui.main_window import MainWindow
    from lume.ui.widgets import app_icon

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)  # a bandeja mantém o app vivo; sair é explícito

    from lume.ui.single_instance import SingleInstance

    instance = SingleInstance()
    if instance.notify_running():
        return 0  # já estava aberto: a outra instância vem para a frente
    instance.listen()
    app.setProperty("lume_mutex", _windows_mutex())  # mantido vivo enquanto o app roda

    # Textos padrão do Qt (botões “Fechar”, “Sim”, “Cancelar”…) em português.
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    translator = QTranslator(app)
    if translator.load(QLocale("pt_BR"), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)

    store = Store.load(config_dir())
    native_contrast = high_contrast_enabled()
    if not native_contrast:
        app.setStyle("Fusion")

    def apply_theme() -> None:
        pt = theme.apply_font(app, store.preferences.ui_scale)
        if native_contrast:
            return  # alto contraste do sistema: respeita as cores do sistema
        theme.apply_palette(app, theme.DARK)
        app.setStyleSheet(theme.stylesheet(theme.DARK, pt))

    apply_theme()

    try:
        backend = create_backend(demo=args.demo)
    except Exception as exc:  # noqa: BLE001
        from lume.platform.mock import MockBackend

        print(f"Backend indisponível ({exc}); abrindo em modo demonstração.", file=sys.stderr)
        backend = MockBackend(label="Modo demonstração (sistema não suportado)")

    controller = Controller(backend)
    window = MainWindow(controller, store, reduced_motion=prefers_reduced_motion())
    window.scaleChanged.connect(lambda _: apply_theme())
    app.aboutToQuit.connect(window.shutdown)
    signal.signal(signal.SIGINT, lambda *_: window.quit_app())
    instance.activated.connect(window.show_window)
    if args.tray and window.tray:
        window.hide()
    else:
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
