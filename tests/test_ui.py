"""Testes de interface com backend simulado (Qt offscreen)."""

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QLabel, QSlider  # noqa: E402

from lume.core.controller import Controller  # noqa: E402
from lume.core.profiles import Store  # noqa: E402
from lume.platform.mock import MockBackend  # noqa: E402
from lume.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture
def make_window(qtbot, tmp_path):
    windows = []

    def factory(backend=None, immediate=True):
        backend = backend or MockBackend()
        store = Store.load(tmp_path)
        store.preferences.apply_immediately = immediate
        ctl = Controller(backend, duration=0.05, sleep=lambda s: None)
        win = MainWindow(ctl, store, reduced_motion=True)
        qtbot.addWidget(win)
        win.show()
        qtbot.waitUntil(lambda: win.caps is not None, timeout=3000)
        windows.append(win)
        return win, backend, ctl

    yield factory
    for w in windows:
        w.shutdown()


def settle(qtbot, ctl):
    ctl.engine.wait_idle()
    qtbot.wait(30)


def test_filters_are_off_by_default_and_unsupported_brightness_is_explained(make_window):
    win, backend, _ = make_window()
    assert not win.filter_toggle.isChecked()
    assert backend.matrix is None
    texts = " ".join(l.text() for l in win.brightness_card.findChildren(QLabel))
    assert "indisponível" in texts and "DDC/CI" in texts
    assert "external" not in win.brightness_sliders


def test_reduced_motion_disables_transitions(make_window):
    win, _, _ = make_window()
    assert win.prefs.transitions is False


def test_immediate_temperature_change_reaches_backend(make_window, qtbot):
    win, backend, ctl = make_window()
    win.temp_slider.slider.setValue(3000)
    settle(qtbot, ctl)
    assert backend.gains[2] < 1.0
    assert "Ajustes" in win.state_pill.text()


def test_manual_mode_waits_for_apply(make_window, qtbot):
    win, backend, ctl = make_window(immediate=False)
    win.temp_slider.slider.setValue(3000)
    settle(qtbot, ctl)
    assert backend.gains == (1.0, 1.0, 1.0)
    assert win.apply_btn.isEnabled()
    win.apply_btn.click()
    settle(qtbot, ctl)
    assert backend.gains[2] < 1.0


def test_filter_needs_explicit_apply_and_reverts_without_confirmation(make_window, qtbot):
    win, backend, ctl = make_window()
    win.filter_toggle.setChecked(True)
    settle(qtbot, ctl)
    assert backend.matrix is None  # só prévia
    win.filter_apply_btn.click()
    settle(qtbot, ctl)
    assert backend.matrix is not None
    assert win.filter_banner.isVisible() and win.confirm_banner.isVisible()
    win._confirm_left = 1
    win._tick_confirm()
    settle(qtbot, ctl)
    assert backend.matrix is None
    assert not win.filter_banner.isVisible()


def test_filter_kept_when_confirmed(make_window, qtbot):
    win, backend, ctl = make_window()
    win.filter_toggle.setChecked(True)
    win.filter_apply_btn.click()
    win._cancel_confirm()
    settle(qtbot, ctl)
    assert backend.matrix is not None and "filtro ativo" in win.windowTitle()


def test_unsupported_filters_are_preview_only(make_window):
    win, _, _ = make_window(MockBackend(filters=False))
    assert not win.filter_apply_btn.isVisibleTo(win)
    assert "prévia" in win.filter_card.pill.text()


def test_restore_and_undo(make_window, qtbot):
    win, backend, ctl = make_window()
    win.brightness_sliders["internal"].slider.setValue(20)
    win.temp_slider.slider.setValue(2500)
    settle(qtbot, ctl)
    win.restore_original()
    settle(qtbot, ctl)
    assert backend.brightness["internal"] == 70 and backend.gains == (1.0, 1.0, 1.0)
    assert win.temp_slider.value() == 6500
    win.undo_restore()
    settle(qtbot, ctl)
    assert backend.brightness["internal"] == 20 and win.temp_slider.value() == 2500


def test_backend_failure_shows_error_and_resyncs_slider(make_window, qtbot):
    win, backend, ctl = make_window(MockBackend(fail={"color"}))
    win.temp_slider.slider.setValue(3000)
    settle(qtbot, ctl)
    qtbot.waitUntil(lambda: win.message_banner.isVisible(), timeout=2000)
    assert "Não foi possível" in win.message_banner.text.text()
    assert win.temp_slider.value() == 6500


def test_profile_save_and_apply(make_window, qtbot, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    win, backend, ctl = make_window()
    win.temp_slider.slider.setValue(4000)
    settle(qtbot, ctl)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("Noite", True))
    win.save_profile()
    assert "Noite" in win.store.profiles
    win.restore_original()
    settle(qtbot, ctl)
    win.apply_profile()
    settle(qtbot, ctl)
    assert win.temp_slider.value() == 4000 and ctl.applied.temperature == 4000


def test_controls_have_accessible_names(make_window):
    win, _, _ = make_window()
    for slider in win.findChildren(QSlider):
        assert slider.accessibleName()
        assert slider.focusPolicy() != 0


def test_minimize_goes_to_tray_when_available(make_window, qtbot):
    win, _, _ = make_window()
    if win.tray is None:
        pytest.skip("sem área de notificação no ambiente de teste")
    win.showMinimized()
    qtbot.waitUntil(lambda: not win.isVisible(), timeout=2000)


def test_update_consent_and_offer(make_window, qtbot, monkeypatch):
    from lume.core import updates

    win, _, _ = make_window()
    upd = win.updater
    assert win.prefs.auto_update is None and not win.act_auto_update.isChecked()
    upd._ask_consent()
    assert win.update_banner.isVisible() and "GitHub" in win.update_banner.text.text()

    release = updates.parse_release({"tag_name": "v9.0.0", "assets": []})
    upd._fetch = lambda: release
    upd.set_auto(True, check_now=True)
    assert win.act_auto_update.isChecked()
    qtbot.waitUntil(lambda: "9.0.0" in win.update_banner.text.text(), timeout=2000)
    # Fora do executável instalado no Windows, só oferece abrir a página: nada é baixado.
    labels = [b.text() for b in win.update_banner.findChildren(type(win.apply_btn))]
    assert "Abrir página da versão" in labels and "Atualizar agora" not in labels


def test_skipped_version_is_not_offered_again(make_window, qtbot):
    from lume.core import updates

    win, _, _ = make_window()
    win.prefs.auto_update = True
    win.prefs.skipped_version = "9.0.0"
    win.updater._fetch = lambda: updates.parse_release({"tag_name": "v9.0.0", "assets": []})
    win.updater.check(manual=False)
    qtbot.waitUntil(lambda: win.prefs.last_update_check > 0, timeout=2000)
    assert not win.update_banner.isVisible()


def test_failed_download_shows_error_and_never_launches(make_window, qtbot):
    from lume.core import updates

    win, _, _ = make_window()
    launched = []
    win.updater._launch = lambda *a, **k: launched.append(a)

    def bad_download(*a, **k):
        raise updates.UpdateError("O arquivo baixado não confere com a assinatura SHA‑256 da release.")

    win.updater._download = bad_download
    win.updater.latest = updates.parse_release({"tag_name": "v9.0.0", "assets": []})
    win.updater._start_download(win.updater.latest)
    qtbot.waitUntil(lambda: "SHA" in win.update_banner.text.text(), timeout=2000)
    assert launched == []
