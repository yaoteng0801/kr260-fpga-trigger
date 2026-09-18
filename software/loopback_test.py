#!/usr/bin/env python3
"""Stage-A deterministic 64-bit AXI DMA loopback test for the KR260."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from software.hw_access import LinuxDmaSession, PynqDmaSession


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=4097, help="non-power-of-two count exercises TLAST")
    parser.add_argument("--dma-uio-name", default="kr260-trigger-dma")
    parser.add_argument("--input-buffer", default="/dev/udmabuf0")
    parser.add_argument("--output-buffer", default="/dev/udmabuf1")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--backend", choices=("uio", "pynq"), default="uio")
    parser.add_argument("--bitstream", type=Path)
    parser.add_argument("--pynq-loader", choices=("bitstream", "overlay"), default="bitstream")
    args = parser.parse_args()
    if args.events <= 0:
        parser.error("--events must be positive")
    if args.backend == "pynq" and args.bitstream is None:
        parser.error("--bitstream is required with --backend pynq")

    indices = np.arange(args.events, dtype=np.uint64)
    source = (indices * np.uint64(0x9E37_79B9_7F4A_7C15)) ^ np.uint64(0xD1A5_CAFE_0123_4567)
    if args.backend == "pynq":
        session_context = PynqDmaSession(
            args.bitstream,
            loader=args.pynq_loader,
            enable_trigger=False,
        )
    else:
        session_context = LinuxDmaSession(
            args.dma_uio_name,
            args.input_buffer,
            args.output_buffer,
        )
    with session_context as session:
        actual, elapsed = session.transfer_array(source, np.dtype("<u8"), source.size, args.timeout)
    mismatch = np.flatnonzero(actual != source)
    throughput = (2 * source.nbytes / elapsed / 1e6) if elapsed else float("inf")
    print(
        f"backend={args.backend} events={source.size} transfer_s={elapsed:.6f} "
        f"bidirectional_MBps={throughput:.3f} "
        f"mismatches={mismatch.size} first_indices={mismatch[:20].tolist()}"
    )
    return 0 if mismatch.size == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
