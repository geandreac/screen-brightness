import json

import pytest

from lume.core.models import Adjustments
from lume.core.profiles import ProfileError, Store


def test_roundtrip(tmp_path):
    store = Store.load(tmp_path)
    adj = Adjustments({"d1": 40}, 3400, 80, "grayscale", 60)
    store.save_profile("  Noite  ", adj)
    store.preferences.ui_scale = 130
    store.preferences.minimize_to_tray = False
    store.save()
    again = Store.load(tmp_path)
    assert again.profiles == {"Noite": adj}
    assert again.preferences.ui_scale == 130 and again.preferences.minimize_to_tray is False


def test_values_are_clamped_and_unknown_filter_dropped(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({
        "profiles": {"X": {"temperature": 99999, "soft_dim": 1, "filter_id": "nope", "brightness": {"a": 500}}}
    }))
    p = Store.load(tmp_path).profiles["X"]
    assert p.temperature == 10000 and p.soft_dim == 20 and p.filter_id is None and p.brightness == {"a": 100}


def test_corrupt_file_is_backed_up(tmp_path):
    (tmp_path / "settings.json").write_text("{nope")
    store = Store.load(tmp_path)
    assert store.load_warning and store.profiles == {}
    assert (tmp_path / "settings.json.bak").exists()


def test_delete_and_name_validation(tmp_path):
    store = Store.load(tmp_path)
    store.save_profile("Dia", Adjustments())
    store.delete_profile("Dia")
    assert Store.load(tmp_path).profiles == {}
    with pytest.raises(ProfileError):
        store.save_profile("   ", Adjustments())
    with pytest.raises(ProfileError):
        store.save_profile("x" * 41, Adjustments())
