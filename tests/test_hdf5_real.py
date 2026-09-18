from pathlib import Path

import h5py
import numpy as np
import pytest

from software.trigger_format import golden_results_packed, pack_events, quantize_thresholds


DATA = Path(__file__).resolve().parents[1] / "Trigger_food_Data.h5"


@pytest.mark.skipif(not DATA.exists(), reason="supplied HDF5 is absent")
def test_supplied_hdf5_metadata_and_chunk():
    expected = {
        f"{sample}_{field}"
        for sample in ("bkg", "tt", "aa")
        for field in ("Npv", "ht", "njet", "score02")
    }
    with h5py.File(DATA, "r") as h5:
        assert set(h5.keys()) == expected
        assert {h5[name].shape for name in expected} == {(1_662_241,)}
        assert {h5[name].dtype for name in expected} == {np.dtype("float32")}
        ht = h5["bkg_ht"][0:20_000]
        ad = h5["bkg_score02"][0:20_000]

    packed = pack_events(ht, ad)
    ht_cut_q, ad_cut_q = quantize_thresholds(218.0, 250.8929737472539)
    result = golden_results_packed(packed, ht_cut_q, ad_cut_q)
    assert packed.shape == (20_000,)
    assert result.shape == (20_000,)
    assert not np.any(result & ~np.uint32(0b111))


@pytest.mark.skipif(not DATA.exists(), reason="supplied HDF5 is absent")
def test_final_partial_chunk_size():
    chunk_size = 20_000
    with h5py.File(DATA, "r") as h5:
        length = h5["bkg_ht"].shape[0]
        begin = (length // chunk_size) * chunk_size
        final = h5["bkg_ht"][begin:length]
    assert length % chunk_size == 2_241
    assert final.shape == (2_241,)
