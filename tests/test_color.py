from lume.core import color
from lume.core.models import MAX_K, MIN_K, NEUTRAL_K


def test_neutral_temperature_is_identity():
    assert color.temperature_multipliers(NEUTRAL_K) == (1.0, 1.0, 1.0)


def test_warm_reduces_blue_and_cool_reduces_red_monotonically():
    prev_blue = 1.0
    for k in range(NEUTRAL_K, MIN_K - 1, -100):
        r, g, b = color.temperature_multipliers(k)
        assert r == 1.0 and b <= prev_blue + 1e-9
        prev_blue = b
    r, g, b = color.temperature_multipliers(MAX_K)
    assert b == 1.0 and r < 1.0


def test_multipliers_never_exceed_one():
    for k in range(MIN_K, MAX_K + 1, 100):
        assert all(0.0 <= c <= 1.0 for c in color.temperature_multipliers(k))


def test_ramps_scale_and_clamp():
    base = color.linear_ramp(256)
    assert base[0] == 0 and base[-1] == 65535
    r, g, b = color.build_ramps((base, base, base), (1.0, 0.5, 2.0))
    assert r == base and g[-1] == round(65535 * 0.5) and b[-1] == 65535


def test_sane_ramp_rejects_garbage():
    assert color.sane_ramp(color.linear_ramp(256))
    assert not color.sane_ramp([20464, 9248, 32637, 0] + [0] * 252)
    assert not color.sane_ramp([0] * 256)
    fixed = color.sane_ramps(([5, 1, 0], [0, 1, 2], [0, 1, 2]))
    assert fixed[0] == color.linear_ramp(3)


def test_filter_strength_zero_is_identity_and_grayscale_rows_equal():
    for fid in color.FILTERS:
        assert color.filter_matrix(fid, 0) == color.IDENTITY
    g = color.filter_matrix("grayscale", 100)
    assert all(abs(a - b) < 1e-9 for row in g for a, b in zip(row, g[0]))
    assert abs(sum(g[0]) - 1.0) < 1e-6


def test_daltonize_filters_keep_neutral_greys_close():
    for fid in ("red_green_d", "red_green_p", "blue_yellow"):
        out = color.transform_rgb((128, 128, 128), (1, 1, 1), color.filter_matrix(fid, 100))
        assert all(abs(c - 128) <= 8 for c in out), (fid, out)


def test_color_effect_layout_is_transposed_5x5():
    m = ((1, 2, 3), (4, 5, 6), (7, 8, 9))
    eff = color.to_color_effect_5x5(m)
    assert len(eff) == 25
    assert eff[0 * 5 + 1] == 4  # linha 0, coluna 1 = m[1][0]
    assert eff[3 * 5 + 3] == 1 and eff[4 * 5 + 4] == 1


def test_transform_applies_gain_after_matrix():
    assert color.transform_rgb((255, 255, 255), (1.0, 0.5, 0.0)) == (255, 128, 0)
