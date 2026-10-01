from argparse import Namespace

import h5py
import numpy as np

from software.adaptive_menu import default_trigger_menu
from software.hw_access_v2 import (
    TriggerV2RegisterLayout,
    configure_v2_register_map,
    v2_identity,
)
from software.kr260_trigger_v2 import run
from software.trigger_v2_format import (
    FEATURE_SCALE,
    ITEM_NAMES,
    N_ITEMS,
    TOTAL_PASS_BIT,
    WORDS_PER_EVENT,
    decode_result,
    default_quantized_cuts,
    golden_results_packed,
    pack_quantized_features,
    quantize_unsigned,
    unpack_feature_words,
)


def test_v2_protocol_order_and_default_register_values():
    menu = default_trigger_menu()
    assert tuple(menu) == ITEM_NAMES
    assert N_ITEMS == 22
    assert WORDS_PER_EVENT == 11
    assert FEATURE_SCALE == 256.0
    assert default_quantized_cuts().tolist() == [
        102400,
        51200,
        40960,
        30720,
        20480,
        102400,
        51200,
        40960,
        30720,
        20480,
        51200,
        51200,
        40960,
        30720,
        20480,
        76800,
        58880,
        51200,
        46080,
        76800,
        256000,
        256000,
    ]


def test_v2_pack_layout_is_two_uint32_items_per_uint64_beat():
    features = np.arange(2 * N_ITEMS, dtype=np.uint32).reshape(2, N_ITEMS)
    words = pack_quantized_features(features)
    assert words.shape == (2 * WORDS_PER_EVENT,)
    assert int(words[0]) == (1 << 32) | 0
    assert int(words[10]) == (21 << 32) | 20
    assert int(words[11]) == (23 << 32) | 22
    assert np.array_equal(unpack_feature_words(words), features)


def test_v2_golden_result_strict_comparison_and_bit_order():
    cuts = np.arange(100, 100 + N_ITEMS, dtype=np.uint32)
    features = np.tile(cuts, (3, 1))
    features[1, [0, 5, 21]] += 1
    features[2, :] += 1
    results = golden_results_packed(pack_quantized_features(features), cuts)
    assert int(results[0]) == 0
    assert int(results[1]) == (1 << 0) | (1 << 5) | (1 << 21) | int(TOTAL_PASS_BIT)
    assert int(results[2]) == (1 << 23) - 1
    decoded = decode_result(int(results[1]))
    assert decoded["items"]["1j"] is True
    assert decoded["items"]["1j_central"] is True
    assert decoded["items"]["VBF"] is True
    assert decoded["total"] is True
    assert decoded["keep_error"] is False


def test_v2_quantization_saturates_and_maps_nan_to_zero():
    values = np.array([-1.0, 0.5 / 256.0, 1.5 / 256.0, np.nan, np.inf])
    assert quantize_unsigned(values).tolist() == [0, 0, 2, 0, 0xFFFF_FFFF]


class FakeRegisters:
    def __init__(self):
        self.values = {
            TriggerV2RegisterLayout.VERSION: TriggerV2RegisterLayout.EXPECTED_VERSION,
            TriggerV2RegisterLayout.CAPABILITIES: TriggerV2RegisterLayout.EXPECTED_CAPABILITIES,
        }

    def write32(self, offset, value):
        self.values[offset] = value

    def read32(self, offset):
        return self.values.get(offset, 0)


def test_v2_register_helper_writes_reads_and_identifies_all_cuts():
    regs = FakeRegisters()
    cuts = np.arange(N_ITEMS, dtype=np.uint32) * 17
    configure_v2_register_map(regs, cuts)
    assert regs.read32(TriggerV2RegisterLayout.cut_offset(21)) == 21 * 17
    assert v2_identity(regs) == (0x0002_0000, 0x0000_003F)


def test_v2_software_only_hdf5_path(tmp_path):
    path = tmp_path / "extended.h5"
    n_events = 7
    with h5py.File(path, "w") as h5:
        h5["bkg_jet_pt"] = np.tile([500, 300, 200, 150, 100, 90], (n_events, 1))
        h5["bkg_cjet_pt"] = np.tile([450, 250, 180, 130, 90, 70], (n_events, 1))
        h5["bkg_fjet_pt"] = np.tile([250, 210, 170, 130, 90, 70], (n_events, 1))
        h5["bkg_ht"] = np.linspace(200, 500, n_events)
        h5["bkg_ht_central"] = np.linspace(150, 450, n_events)
        h5["bkg_met"] = np.linspace(100, 300, n_events)
        h5["bkg_met_central"] = np.linspace(80, 260, n_events)
        h5["bkg_score02"] = np.linspace(100, 500, n_events)
        h5["bkg_pair_mjj"] = np.tile([800, 1200, 900], (n_events, 1))
        h5["bkg_pair_min_pt"] = np.tile([40, 60, 70], (n_events, 1))
        h5["bkg_pair_deta"] = np.tile([1, 3, 4], (n_events, 1))

    args = Namespace(
        hdf5=path,
        sample="bkg",
        start=0,
        count=7,
        chunk_size=3,
        cuts_json=None,
        cut=[],
        absolute_vbf_deta=False,
        adaptive_mode="none",
        target_rate=100_000.0,
        input_rate=40_000_000.0,
        memory_size=5,
        software_only=True,
        backend="uio",
        bitstream=None,
        pynq_buffer_size=4 * 1024 * 1024,
        pynq_loader="bitstream",
        pynq_clock_mhz=100.0,
        dma_uio_name="unused",
        trigger_uio_name="unused",
        input_buffer="unused",
        output_buffer="unused",
        timeout=1.0,
        max_mismatch_indices=20,
        json_report=None,
    )
    report = run(args)
    assert report["events"] == 7
    assert report["chunks"] == 3
    assert report["words_per_event"] == 11
    assert report["mismatches"] == 0
    assert report["keep_errors"] == 0
    assert report["framing_errors"] == 0
    assert report["hardware_executed"] is False
