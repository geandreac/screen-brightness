import threading

from lume.core.controller import Controller
from lume.core.engine import Applier, ApplyEngine, interpolate
from lume.core.models import Adjustments
from lume.platform.mock import MockBackend


def make(backend=None, **kw):
    backend = backend or MockBackend()
    results = []
    ctl = Controller(backend, results.append, duration=0.1, sleep=lambda s: None, **kw)
    ctl.initialize()
    return ctl, backend, results


def test_initialize_reads_original_brightness_only_for_supported_displays():
    ctl, _, _ = make()
    assert ctl.original.brightness == {"internal": 70}
    ctl.shutdown()


def test_unsupported_display_brightness_is_never_sent():
    ctl, backend, results = make()
    ctl.request(ctl.original.with_brightness("external", 10), animate=False)
    ctl.engine.wait_idle()
    assert not any(c[0] == "brightness" for c in backend.calls)
    assert results[-1].errors == ()
    ctl.shutdown()


def test_animated_transition_has_intermediate_steps_and_exact_final():
    ctl, backend, results = make()
    ctl.request(ctl.original.with_(temperature=3000), animate=True)
    ctl.engine.wait_idle()
    colors = [c for c in backend.calls if c[0] == "color"]
    assert len(colors) > 1
    assert results[-1].actual.temperature == 3000
    ctl.shutdown()


def test_no_transition_means_single_step():
    ctl, backend, _ = make()
    ctl.request(ctl.original.with_(temperature=3000, soft_dim=60), animate=False)
    ctl.engine.wait_idle()
    assert len([c for c in backend.calls if c[0] == "color"]) == 1
    ctl.shutdown()


def test_restore_original_returns_to_identity():
    ctl, backend, _ = make()
    ctl.request(ctl.original.with_(temperature=2500, filter_id="grayscale").with_brightness("internal", 30), animate=False)
    ctl.engine.wait_idle()
    assert backend.matrix is not None and backend.brightness["internal"] == 30
    ctl.restore_original(animate=True)
    ctl.engine.wait_idle()
    assert backend.gains == (1.0, 1.0, 1.0)
    assert backend.matrix is None
    assert backend.brightness["internal"] == 70
    ctl.shutdown()


def test_failure_is_reported_and_state_reconciled():
    backend = MockBackend(fail={"color"})
    ctl, _, results = make(backend)
    ctl.request(ctl.original.with_(temperature=3000).with_brightness("internal", 40), animate=False)
    ctl.engine.wait_idle()
    res = results[-1]
    assert [e.feature for e in res.errors] == ["color"]
    assert res.actual.temperature == 6500 and res.actual.brightness["internal"] == 40
    ctl.reconcile(res)
    assert ctl.target.temperature == 6500 and ctl.target.brightness["internal"] == 40
    ctl.shutdown()


def test_unsupported_filter_reports_explanation():
    backend = MockBackend(filters=False)
    ctl, _, results = make(backend)
    ctl.request(ctl.original.with_(filter_id="grayscale"), animate=False)
    ctl.engine.wait_idle()
    err = results[-1].errors[0]
    assert err.feature == "filter" and err.error.message
    assert backend.matrix is None
    ctl.shutdown()


def test_compare_shows_original_colors_and_comes_back():
    ctl, backend, _ = make()
    target = ctl.original.with_(temperature=3000, filter_id="grayscale")
    ctl.request(target, animate=False)
    ctl.engine.wait_idle()
    ctl.compare(True)
    ctl.engine.wait_idle()
    assert backend.gains == (1.0, 1.0, 1.0) and backend.matrix is None
    ctl.compare(False)
    ctl.engine.wait_idle()
    assert backend.matrix is not None and ctl.applied.temperature == 3000
    ctl.shutdown()


def test_shutdown_restores_color():
    ctl, backend, _ = make()
    ctl.request(ctl.original.with_(temperature=3000), animate=False)
    ctl.engine.wait_idle()
    ctl.shutdown()
    assert backend.restored == 1 and backend.gains == (1.0, 1.0, 1.0)


def test_newer_request_interrupts_transition():
    backend = MockBackend()
    caps = backend.probe()
    gate = threading.Event()
    engine = None

    def sleep(_):
        if not gate.is_set():
            gate.set()
            engine.request(Adjustments(temperature=9000), False)

    results = []
    engine = ApplyEngine(Applier(backend, caps, Adjustments()), results.append, duration=1, sleep=sleep)
    engine.start()
    engine.request(Adjustments(temperature=2000), True)
    assert engine.wait_idle()
    engine.stop()
    assert results[0].completed is False
    assert results[-1].actual.temperature == 9000


def test_interpolate_filter_switch_fades_out_then_in():
    a = Adjustments(filter_id="grayscale", filter_strength=100)
    b = Adjustments(filter_id="blue_yellow", filter_strength=100)
    assert interpolate(a, b, 0.25).filter_id == "grayscale"
    assert interpolate(a, b, 0.75).filter_id == "blue_yellow"
    assert interpolate(a, b, 1) == b
