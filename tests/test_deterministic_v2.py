import numpy as np

from software.deterministic_trigger_test_v2 import directed_vectors
from software.trigger_v2_format import (
    N_ITEMS,
    TOTAL_PASS_BIT,
    default_quantized_cuts,
    golden_results_packed,
    pack_quantized_features,
)


def test_directed_vectors_cover_strict_boundary_and_every_item_bit():
    cuts = default_quantized_cuts()
    features = directed_vectors(cuts)
    results = golden_results_packed(pack_quantized_features(features), cuts)

    assert features.shape == (3 + 3 * N_ITEMS, N_ITEMS)
    assert int(results[0]) == 0
    assert int(results[1]) == 0
    assert int(results[2]) == (1 << 23) - 1
    for index in range(N_ITEMS):
        assert int(results[3 + 3 * index]) == (1 << index) | int(TOTAL_PASS_BIT)
        assert int(results[4 + 3 * index]) == 0
        assert int(results[5 + 3 * index]) == 0


def test_directed_vectors_are_uint32_and_pack_to_eleven_beats_per_event():
    features = directed_vectors(default_quantized_cuts())
    packed = pack_quantized_features(features)
    assert features.dtype == np.uint32
    assert packed.dtype == np.dtype("<u8")
    assert packed.size == features.shape[0] * 11
