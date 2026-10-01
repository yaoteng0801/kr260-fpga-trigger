#!/usr/bin/env python3
"""Directed board test for the KR260 22-item V2 trigger datapath."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from pathlib import Path
import sys

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from software.hw_access import HardwareAccessError, LinuxDmaSession, PynqDmaSession
from software.hw_access_v2 import (
    TriggerV2RegisterLayout,
    TriggerV2Registers,
    configure_v2_register_map,
    v2_identity,
)
from software.trigger_v2_format import (
    ITEM_NAMES,
    N_ITEMS,
    default_quantized_cuts,
    golden_results_quantized,
    pack_quantized_features,
)


def directed_vectors(cuts_q: np.ndarray) -> np.ndarray:
    """Build cases for all-low, all-equal, all-pass, and every item bit."""

    cuts = np.asarray(cuts_q, dtype=np.uint32)
    if cuts.shape != (N_ITEMS,):
        raise ValueError(f"cuts must have shape ({N_ITEMS},)")
    if np.any(cuts == np.iinfo(np.uint32).max):
        raise ValueError("directed test requires thresholds below UINT32_MAX")

    rows = [
        np.zeros(N_ITEMS, dtype=np.uint32),
        cuts.copy(),
        cuts + np.uint32(1),
    ]
    for index in range(N_ITEMS):
        one_pass = np.zeros(N_ITEMS, dtype=np.uint32)
        one_pass[index] = cuts[index] + np.uint32(1)
        rows.append(one_pass)

        equal = np.zeros(N_ITEMS, dtype=np.uint32)
        equal[index] = cuts[index]
        rows.append(equal)

        below = np.zeros(N_ITEMS, dtype=np.uint32)
        below[index] = cuts[index] - np.uint32(1) if cuts[index] else np.uint32(0)
        rows.append(below)
    return np.stack(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("uio", "pynq"), default="uio")
    parser.add_argument("--bitstream", type=Path)
    parser.add_argument("--pynq-loader", choices=("bitstream", "overlay"), default="bitstream")
    parser.add_argument("--pynq-buffer-size", type=int, default=4 * 1024 * 1024)
    parser.add_argument("--pynq-clock-mhz", type=float, default=100.0)
    parser.add_argument("--dma-uio-name", default="kr260-trigger-v2-dma")
    parser.add_argument("--trigger-uio-name", default="kr260-axis-trigger-v2")
    parser.add_argument("--input-buffer", default="/dev/udmabuf0")
    parser.add_argument("--output-buffer", default="/dev/udmabuf1")
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def run(args: argparse.Namespace) -> None:
    if args.backend == "pynq" and args.bitstream is None:
        raise ValueError("--bitstream is required with --backend pynq")
    if args.timeout <= 0 or args.pynq_buffer_size <= 0 or args.pynq_clock_mhz <= 0:
        raise ValueError("timeouts, buffer sizes, and clocks must be positive")

    cuts_q = default_quantized_cuts()
    features_q = directed_vectors(cuts_q)
    packed = pack_quantized_features(features_q)
    expected = golden_results_quantized(features_q, cuts_q)

    with ExitStack() as stack:
        if args.backend == "pynq":
            dma = stack.enter_context(
                PynqDmaSession(
                    args.bitstream,
                    buffer_size=args.pynq_buffer_size,
                    loader=args.pynq_loader,
                    clock_mhz=args.pynq_clock_mhz,
                )
            )
            if dma.trigger_regs is None:
                raise HardwareAccessError("PYNQ session did not create trigger MMIO")
            version, capabilities = v2_identity(dma.trigger_regs)
            configure_v2_register_map(dma.trigger_regs, cuts_q)
        else:
            dma = stack.enter_context(
                LinuxDmaSession(
                    dma_uio_name=args.dma_uio_name,
                    input_device=args.input_buffer,
                    output_device=args.output_buffer,
                )
            )
            trigger = stack.enter_context(TriggerV2Registers(args.trigger_uio_name))
            version, capabilities = trigger.identity()
            trigger.configure(cuts_q)

        if version != TriggerV2RegisterLayout.EXPECTED_VERSION:
            raise HardwareAccessError(
                f"wrong trigger version 0x{version:08x}; expected "
                f"0x{TriggerV2RegisterLayout.EXPECTED_VERSION:08x}"
            )
        required = TriggerV2RegisterLayout.EXPECTED_CAPABILITIES
        if capabilities & required != required:
            raise HardwareAccessError(
                f"missing V2 capabilities: read 0x{capabilities:08x}, "
                f"required 0x{required:08x}"
            )

        actual, elapsed = dma.transfer_array(
            packed,
            np.dtype("<u4"),
            features_q.shape[0],
            timeout_s=args.timeout,
        )

    mismatch = np.flatnonzero(actual != expected)
    if mismatch.size:
        details = ", ".join(
            f"event {int(index)}: got 0x{int(actual[index]):08x}, "
            f"expected 0x{int(expected[index]):08x}"
            for index in mismatch[:10]
        )
        raise HardwareAccessError(
            f"V2 directed test found {mismatch.size} mismatches; {details}"
        )

    print(
        f"PASS: V2 identity=0x{version:08x}, capabilities=0x{capabilities:08x}, "
        f"events={features_q.shape[0]}, items={len(ITEM_NAMES)}, "
        f"DMA={elapsed * 1e3:.3f} ms, mismatches=0"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except (HardwareAccessError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
