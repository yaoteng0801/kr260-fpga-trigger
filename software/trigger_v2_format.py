"""Canonical PS/PL format and golden model for the 22-item V2 trigger."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from software.adaptive_menu import Chunk, Menu, default_trigger_menu, item_values


ITEM_NAMES = (
    "1j",
    "3j",
    "4j",
    "5j",
    "6j",
    "1j_central",
    "3j_central",
    "4j_central",
    "5j_central",
    "6j_central",
    "1j_forward",
    "3j_forward",
    "4j_forward",
    "5j_forward",
    "6j_forward",
    "HT",
    "HT_central",
    "MET",
    "MET_central",
    "AD",
    "dijet_mass",
    "VBF",
)

N_ITEMS = len(ITEM_NAMES)
FEATURE_SCALE = 256.0
WORDS_PER_EVENT = N_ITEMS // 2
UINT32_MAX = np.iinfo(np.uint32).max

TOTAL_PASS_BIT = np.uint32(1 << 22)
KEEP_ERROR_BIT = np.uint32(1 << 23)
FRAMING_ERROR_BIT = np.uint32(1 << 24)
ITEM_MASK = np.uint32((1 << N_ITEMS) - 1)


def validate_v2_menu(menu: Mapping[str, Mapping[str, Any]]) -> None:
    names = tuple(menu)
    if names != ITEM_NAMES:
        raise ValueError(
            "V2 menu order is part of the hardware protocol; "
            f"expected {ITEM_NAMES}, got {names}"
        )


def quantize_unsigned(values: np.ndarray, scale: float = FEATURE_SCALE) -> np.ndarray:
    """Round-to-nearest/even, saturate to uint32, and map NaN to zero."""

    if scale <= 0:
        raise ValueError("scale must be positive")
    array = np.asarray(values, dtype=np.float64)
    safe = np.nan_to_num(
        array,
        nan=0.0,
        posinf=float(UINT32_MAX) / scale,
        neginf=0.0,
    )
    rounded = np.rint(safe * scale)
    return np.clip(rounded, 0.0, float(UINT32_MAX)).astype("<u4")


def feature_matrix(chunk: Chunk, menu: Menu | None = None) -> np.ndarray:
    """Return floating event variables in the exact V2 hardware item order."""

    active_menu = default_trigger_menu() if menu is None else menu
    validate_v2_menu(active_menu)
    columns = [np.asarray(item_values(chunk, active_menu[name])) for name in ITEM_NAMES]
    if not columns:
        return np.empty((0, N_ITEMS), dtype=np.float64)
    lengths = {column.shape[0] for column in columns}
    if len(lengths) != 1:
        raise ValueError("V2 item variables have different event counts")
    return np.column_stack(columns)


def quantize_cuts(
    cuts: Mapping[str, float],
    menu: Mapping[str, Mapping[str, Any]] | None = None,
) -> np.ndarray:
    """Return the 22 uint32 thresholds in register/wire order."""

    if menu is not None:
        validate_v2_menu(menu)
    missing = [name for name in ITEM_NAMES if name not in cuts]
    if missing:
        raise KeyError(f"missing V2 cuts: {missing}")
    return quantize_unsigned(np.asarray([cuts[name] for name in ITEM_NAMES]))


def default_quantized_cuts(*, absolute_vbf_deta: bool = False) -> np.ndarray:
    menu = default_trigger_menu(absolute_vbf_deta=absolute_vbf_deta)
    return quantize_cuts({name: config["cut"] for name, config in menu.items()}, menu)


def pack_quantized_features(features_q: np.ndarray) -> np.ndarray:
    """Pack `(events, 22)` uint32 variables into 11 little-endian uint64 beats."""

    values = np.asarray(features_q, dtype="<u4")
    if values.ndim != 2 or values.shape[1] != N_ITEMS:
        raise ValueError(f"features must have shape (events, {N_ITEMS})")
    contiguous = np.ascontiguousarray(values)
    return contiguous.reshape(-1).view("<u8").copy()


def pack_features(features: np.ndarray) -> np.ndarray:
    return pack_quantized_features(quantize_unsigned(features))


def unpack_feature_words(words: np.ndarray) -> np.ndarray:
    packed = np.ascontiguousarray(np.asarray(words, dtype="<u8")).reshape(-1)
    if packed.size % WORDS_PER_EVENT:
        raise ValueError(
            f"V2 input has {packed.size} words, not a multiple of {WORDS_PER_EVENT}"
        )
    return packed.view("<u4").reshape(-1, N_ITEMS).copy()


def golden_results_quantized(features_q: np.ndarray, cuts_q: np.ndarray) -> np.ndarray:
    """Return item bits `[21:0]` plus combined OR bit 22."""

    features = np.asarray(features_q, dtype=np.uint32)
    cuts = np.asarray(cuts_q, dtype=np.uint32)
    if features.ndim != 2 or features.shape[1] != N_ITEMS:
        raise ValueError(f"features must have shape (events, {N_ITEMS})")
    if cuts.shape != (N_ITEMS,):
        raise ValueError(f"cuts must have shape ({N_ITEMS},)")
    passed = features > cuts[np.newaxis, :]
    result = np.zeros(features.shape[0], dtype=np.uint32)
    for index in range(N_ITEMS):
        result |= passed[:, index].astype(np.uint32) << np.uint32(index)
    result |= np.any(passed, axis=1).astype(np.uint32) * TOTAL_PASS_BIT
    return result


def golden_results_packed(words: np.ndarray, cuts_q: np.ndarray) -> np.ndarray:
    return golden_results_quantized(unpack_feature_words(words), cuts_q)


def decode_result(word: int) -> dict[str, Any]:
    value = int(word) & 0xFFFF_FFFF
    return {
        "items": {name: bool(value & (1 << index)) for index, name in enumerate(ITEM_NAMES)},
        "total": bool(value & int(TOTAL_PASS_BIT)),
        "keep_error": bool(value & int(KEEP_ERROR_BIT)),
        "framing_error": bool(value & int(FRAMING_ERROR_BIT)),
    }
