#!/usr/bin/env python3
"""Stage-C deterministic integrated DMA/trigger test."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from pathlib import Path
import sys

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from software.hw_access import LinuxDmaSession, PynqDmaSession, TriggerRegisters
from software.trigger_format import golden_results_packed, pack_events, quantize_thresholds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ht-cut", type=float, default=100.0)
    parser.add_argument("--ad-cut", type=float, default=10.0)
    parser.add_argument("--dma-uio-name", default="kr260-trigger-dma")
    parser.add_argument("--trigger-uio-name", default="kr260-axis-trigger")
    parser.add_argument("--input-buffer", default="/dev/udmabuf0")
    parser.add_argument("--output-buffer", default="/dev/udmabuf1")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--backend", choices=("uio", "pynq"), default="uio")
    parser.add_argument("--bitstream", type=Path)
    parser.add_argument("--pynq-loader", choices=("bitstream", "overlay"), default="bitstream")
    args = parser.parse_args()
    if args.backend == "pynq" and args.bitstream is None:
        parser.error("--bitstream is required with --backend pynq")

    ht = np.asarray([0, 99.5, 100, 100.5, 100, 100.5, 1, 1000, 2], dtype=np.float32)
    ad = np.asarray([0, 10, 10, 10, 10.00390625, 10.00390625, 100, 0, 2], dtype=np.float32)
    packed = pack_events(ht, ad)
    ht_q, ad_q = quantize_thresholds(args.ht_cut, args.ad_cut)
    expected = golden_results_packed(packed, ht_q, ad_q)

    with ExitStack() as stack:
        if args.backend == "pynq":
            session = stack.enter_context(
                PynqDmaSession(args.bitstream, loader=args.pynq_loader)
            )
            session.configure_trigger(ht_q, ad_q)
            version, capabilities = session.trigger_identity()
        else:
            session = stack.enter_context(
                LinuxDmaSession(args.dma_uio_name, args.input_buffer, args.output_buffer)
            )
            trigger = stack.enter_context(TriggerRegisters(args.trigger_uio_name))
            trigger.configure(ht_q, ad_q)
            version = trigger.regs.read32(TriggerRegisters.VERSION)
            capabilities = trigger.regs.read32(TriggerRegisters.CAPABILITIES)
        actual, elapsed = session.transfer_array(packed, np.dtype("<u4"), packed.size, args.timeout)

    mismatch = np.flatnonzero(actual != expected)
    print(f"backend={args.backend} version=0x{version:08x} capabilities=0x{capabilities:08x}")
    print(f"actual={actual.tolist()}")
    print(f"expected={expected.tolist()}")
    print(f"events={packed.size} transfer_s={elapsed:.6f} mismatches={mismatch.size} indices={mismatch.tolist()}")
    return 0 if mismatch.size == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
