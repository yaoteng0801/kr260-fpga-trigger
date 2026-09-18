"""Canonical PS/PL data format and NumPy golden model.

The functions in this module are the single source of truth for host packing,
threshold conversion, and expected result generation.
"""

from __future__ import annotations

import numpy as np

HT_SCALE = 2.0
AD_SCALE = 256.0
UINT32_MAX = np.iinfo(np.uint32).max

HT_SHIFT = 0
AD_SHIFT = 32

HT_PASS_BIT = np.uint32(1 << 0)
AD_PASS_BIT = np.uint32(1 << 1)
TOTAL_PASS_BIT = np.uint32(1 << 2)
KEEP_ERROR_BIT = np.uint32(1 << 3)


def quantize_unsigned(values: np.ndarray, scale: float) -> np.ndarray:
    """Round to nearest/even, saturate to uint32, and map NaN to zero.

    Positive infinity saturates high and negative infinity saturates low. The
    computation is deliberately performed in float64 so scalar thresholds and
    float32 HDF5 arrays follow one implementation.
    """

    array = np.asarray(values, dtype=np.float64)
    safe = np.nan_to_num(
        array,
        nan=0.0,
        posinf=float(UINT32_MAX),
        neginf=0.0,
    )
    rounded = np.rint(safe * scale)
    return np.clip(rounded, 0.0, float(UINT32_MAX)).astype(np.uint32)


def quantize_ht(values: np.ndarray) -> np.ndarray:
    return quantize_unsigned(values, HT_SCALE)


def quantize_ad(values: np.ndarray) -> np.ndarray:
    return quantize_unsigned(values, AD_SCALE)


def quantize_thresholds(ht_cut: float, ad_cut: float) -> tuple[int, int]:
    ht_q = int(quantize_ht(np.asarray([ht_cut]))[0])
    ad_q = int(quantize_ad(np.asarray([ad_cut]))[0])
    return ht_q, ad_q


def pack_events(ht: np.ndarray, ad: np.ndarray) -> np.ndarray:
    """Return little-endian uint64 events: AD[63:32], HT[31:0]."""

    ht_q = quantize_ht(ht)
    ad_q = quantize_ad(ad)
    if ht_q.shape != ad_q.shape:
        raise ValueError(f"HT and AD shapes differ: {ht_q.shape} != {ad_q.shape}")
    return (ad_q.astype(np.uint64) << np.uint64(AD_SHIFT)) | ht_q.astype(np.uint64)


def unpack_events(events: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    words = np.asarray(events, dtype=np.uint64)
    ht_q = (words & np.uint64(UINT32_MAX)).astype(np.uint32)
    ad_q = (words >> np.uint64(AD_SHIFT)).astype(np.uint32)
    return ht_q, ad_q


def golden_results_quantized(
    ht_q: np.ndarray,
    ad_q: np.ndarray,
    ht_cut_q: int,
    ad_cut_q: int,
) -> np.ndarray:
    """Apply the PL's exact unsigned strict-greater comparisons."""

    ht_array = np.asarray(ht_q, dtype=np.uint32)
    ad_array = np.asarray(ad_q, dtype=np.uint32)
    if ht_array.shape != ad_array.shape:
        raise ValueError(f"HT and AD shapes differ: {ht_array.shape} != {ad_array.shape}")
    ht_pass = ht_array > np.uint32(ht_cut_q)
    ad_pass = ad_array > np.uint32(ad_cut_q)
    total_pass = ht_pass | ad_pass
    return (
        ht_pass.astype(np.uint32) * HT_PASS_BIT
        | ad_pass.astype(np.uint32) * AD_PASS_BIT
        | total_pass.astype(np.uint32) * TOTAL_PASS_BIT
    )


def golden_results_packed(events: np.ndarray, ht_cut_q: int, ad_cut_q: int) -> np.ndarray:
    ht_q, ad_q = unpack_events(events)
    return golden_results_quantized(ht_q, ad_q, ht_cut_q, ad_cut_q)
