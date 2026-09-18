import numpy as np

from software.trigger_format import (
    AD_SCALE,
    HT_SCALE,
    UINT32_MAX,
    golden_results_packed,
    pack_events,
    quantize_ad,
    quantize_ht,
    quantize_thresholds,
    unpack_events,
)


def test_observed_ranges_fit_format():
    assert quantize_ht(np.array([4228.5], dtype=np.float32))[0] == 8457
    assert quantize_ad(np.array([126716.0], dtype=np.float32))[0] == 32_439_296
    assert HT_SCALE == 2.0
    assert AD_SCALE == 256.0


def test_round_nearest_even_saturation_and_nonfinite_policy():
    values = np.array([-1.0, 0.25, 0.75, np.nan, np.inf, -np.inf])
    got = quantize_ht(values)
    assert got.tolist() == [0, 0, 2, 0, int(UINT32_MAX), 0]


def test_pack_unpack_bit_positions():
    ht = np.array([1.0, 100.5], dtype=np.float32)
    ad = np.array([2.0, 10.25], dtype=np.float32)
    packed = pack_events(ht, ad)
    ht_q, ad_q = unpack_events(packed)
    assert ht_q.tolist() == [2, 201]
    assert ad_q.tolist() == [512, 2624]
    assert int(packed[0]) == (512 << 32) | 2


def test_strict_trigger_cases():
    ht_cut_q, ad_cut_q = quantize_thresholds(100.0, 10.0)
    ht = np.array([99.5, 100.0, 100.5, 100.0, 100.5])
    ad = np.array([9.0, 10.0, 10.0, 10.00390625, 10.00390625])
    got = golden_results_packed(pack_events(ht, ad), ht_cut_q, ad_cut_q)
    assert got.tolist() == [0, 0, 0b101, 0b110, 0b111]


def test_shape_mismatch_rejected():
    with np.testing.assert_raises(ValueError):
        pack_events(np.zeros(2), np.zeros(3))
