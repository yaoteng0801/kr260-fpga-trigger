#!/usr/bin/env python3
"""Stream HDF5 HT/score02 chunks through the KR260 trigger pipeline."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import time

import h5py
import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from software.hw_access import LinuxDmaSession, PynqDmaSession, TriggerRegisters
from software.trigger_format import (
    KEEP_ERROR_BIT,
    golden_results_packed,
    pack_events,
    quantize_thresholds,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hdf5", type=Path, help="HDF5 file on the SD card")
    parser.add_argument("--sample", choices=("bkg", "tt", "aa"), default="bkg")
    parser.add_argument("--ht-dataset", help="override <sample>_ht")
    parser.add_argument("--ad-dataset", help="override <sample>_score02")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, help="events to process; default is through dataset end")
    parser.add_argument("--chunk-size", type=int, default=20_000)
    parser.add_argument("--ht-cut", type=float, default=218.0)
    parser.add_argument("--ad-cut", type=float, default=250.8929737472539)
    parser.add_argument("--software-only", action="store_true", help="exercise HDF5, packing, and golden model without PL")
    parser.add_argument("--backend", choices=("uio", "pynq"), default="uio")
    parser.add_argument(
        "--bitstream",
        type=Path,
        help="PYNQ .bit file; overlay loader also requires a matching .hwh",
    )
    parser.add_argument("--pynq-buffer-size", type=int, default=4 * 1024 * 1024)
    parser.add_argument("--pynq-loader", choices=("bitstream", "overlay"), default="bitstream")
    parser.add_argument("--pynq-clock-mhz", type=float, default=100.0)
    parser.add_argument("--dma-uio-name", default="kr260-trigger-dma")
    parser.add_argument("--trigger-uio-name", default="kr260-axis-trigger")
    parser.add_argument("--input-buffer", default="/dev/udmabuf0")
    parser.add_argument("--output-buffer", default="/dev/udmabuf1")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--max-mismatch-indices", type=int, default=20)
    parser.add_argument("--json-report", type=Path)
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.start < 0:
        raise ValueError("--start must be nonnegative")
    if args.count is not None and args.count < 0:
        raise ValueError("--count must be nonnegative")
    if args.chunk_size <= 0:
        raise ValueError("--chunk-size must be positive")
    if args.timeout <= 0:
        raise ValueError("--timeout must be positive")
    if getattr(args, "pynq_buffer_size", 4 * 1024 * 1024) <= 0:
        raise ValueError("--pynq-buffer-size must be positive")
    if getattr(args, "pynq_clock_mhz", 100.0) <= 0:
        raise ValueError("--pynq-clock-mhz must be positive")
    if not args.software_only and getattr(args, "backend", "uio") == "pynq":
        if getattr(args, "bitstream", None) is None:
            raise ValueError("--bitstream is required with --backend pynq")


def run(args: argparse.Namespace) -> dict[str, object]:
    _validate_args(args)
    ht_name = args.ht_dataset or f"{args.sample}_ht"
    ad_name = args.ad_dataset or f"{args.sample}_score02"
    ht_cut_q, ad_cut_q = quantize_thresholds(args.ht_cut, args.ad_cut)

    total_events = 0
    total_hdf5_s = 0.0
    total_dma_s = 0.0
    mismatch_count = 0
    mismatch_indices: list[int] = []
    keep_error_count = 0
    chunks = 0

    with ExitStack() as stack:
        h5 = stack.enter_context(h5py.File(args.hdf5, "r"))
        for name in (ht_name, ad_name):
            if name not in h5:
                raise KeyError(f"dataset {name!r} not found; available: {sorted(h5.keys())}")
        ht_dataset = h5[ht_name]
        ad_dataset = h5[ad_name]
        if ht_dataset.ndim != 1 or ad_dataset.ndim != 1:
            raise ValueError("HT and AD datasets must both be one-dimensional")
        if ht_dataset.shape != ad_dataset.shape:
            raise ValueError(f"dataset shapes differ: {ht_dataset.shape} != {ad_dataset.shape}")
        ht_dtype = str(ht_dataset.dtype)
        ad_dtype = str(ad_dataset.dtype)

        dataset_length = int(ht_dataset.shape[0])
        stop = dataset_length if args.count is None else min(dataset_length, args.start + args.count)
        if args.start > dataset_length:
            raise ValueError(f"--start {args.start} exceeds dataset length {dataset_length}")

        dma = None
        hardware_backend = "software"
        trigger_version = None
        trigger_capabilities = None
        if not args.software_only:
            hardware_backend = getattr(args, "backend", "uio")
            if hardware_backend == "pynq":
                dma = stack.enter_context(
                    PynqDmaSession(
                        args.bitstream,
                        buffer_size=getattr(args, "pynq_buffer_size", 4 * 1024 * 1024),
                        loader=getattr(args, "pynq_loader", "bitstream"),
                        clock_mhz=getattr(args, "pynq_clock_mhz", 100.0),
                    )
                )
                dma.configure_trigger(ht_cut_q, ad_cut_q)
                trigger_version, trigger_capabilities = dma.trigger_identity()
            else:
                dma = stack.enter_context(
                    LinuxDmaSession(
                        dma_uio_name=args.dma_uio_name,
                        input_device=args.input_buffer,
                        output_device=args.output_buffer,
                    )
                )
                trigger = stack.enter_context(TriggerRegisters(args.trigger_uio_name))
                trigger.configure(ht_cut_q, ad_cut_q)
                trigger_version = trigger.regs.read32(TriggerRegisters.VERSION)
                trigger_capabilities = trigger.regs.read32(TriggerRegisters.CAPABILITIES)

        for begin in range(args.start, stop, args.chunk_size):
            end = min(begin + args.chunk_size, stop)
            read_start = time.perf_counter()
            # h5py hyperslabs load only this requested chunk.
            ht = ht_dataset[begin:end]
            ad = ad_dataset[begin:end]
            total_hdf5_s += time.perf_counter() - read_start

            packed = pack_events(ht, ad)
            expected = golden_results_packed(packed, ht_cut_q, ad_cut_q)
            if dma is None:
                actual = expected.copy()
                dma_elapsed = 0.0
            else:
                actual, dma_elapsed = dma.transfer_array(
                    packed,
                    np.dtype("<u4"),
                    packed.size,
                    timeout_s=args.timeout,
                )
            total_dma_s += dma_elapsed

            keep_error_count += int(np.count_nonzero(actual & KEEP_ERROR_BIT))
            unequal = np.flatnonzero(actual != expected)
            mismatch_count += int(unequal.size)
            remaining = max(0, args.max_mismatch_indices - len(mismatch_indices))
            mismatch_indices.extend((begin + unequal[:remaining]).tolist())
            total_events += int(packed.size)
            chunks += 1

    input_bytes = total_events * 8
    result_bytes = total_events * 4
    report: dict[str, object] = {
        "file": str(args.hdf5),
        "sample": args.sample,
        "ht_dataset": ht_name,
        "ad_dataset": ad_name,
        "source_dtype_ht": ht_dtype,
        "source_dtype_ad": ad_dtype,
        "start": args.start,
        "stop": stop,
        "events": total_events,
        "chunks": chunks,
        "ht_cut": args.ht_cut,
        "ad_cut": args.ad_cut,
        "ht_cut_quantized": ht_cut_q,
        "ad_cut_quantized": ad_cut_q,
        "hdf5_read_seconds": total_hdf5_s,
        "dma_seconds": total_dma_s,
        "dma_bytes_bidirectional": input_bytes + result_bytes,
        "dma_throughput_MBps": ((input_bytes + result_bytes) / total_dma_s / 1e6) if total_dma_s else None,
        "trigger_throughput_events_per_second": (total_events / total_dma_s) if total_dma_s else None,
        "mismatches": mismatch_count,
        "mismatch_indices": mismatch_indices,
        "keep_errors": keep_error_count,
        "hardware_executed": not args.software_only,
        "hardware_backend": hardware_backend,
        "trigger_version": trigger_version,
        "trigger_capabilities": trigger_capabilities,
        "bitstream": str(args.bitstream) if getattr(args, "bitstream", None) else None,
        "pynq_loader": (
            getattr(args, "pynq_loader", None) if hardware_backend == "pynq" else None
        ),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["mismatches"] == 0 and report["keep_errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
