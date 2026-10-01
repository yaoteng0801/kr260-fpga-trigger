#!/usr/bin/env python3
"""Run the extended adaptive trigger menu on chunked HDF5 data.

This is a PS/offline reference application.  It does not load or replace the
deployed two-item KR260 bitstream.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Iterable

import h5py
import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from software.adaptive_menu import (  # noqa: E402
    AdaptiveMenuController,
    CostWeights,
    default_trigger_menu,
    required_sources,
    suggest_initial_menu,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hdf5", type=Path, help="extended trigger-food HDF5 file")
    parser.add_argument("--sample", default="bkg", help="background sample prefix")
    parser.add_argument(
        "--signal-samples",
        nargs="*",
        default=(),
        metavar="SAMPLE",
        help="optional truth-labelled samples for offline efficiency cost, e.g. tt aa",
    )
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument(
        "--count",
        type=int,
        default=100_000,
        help="events to process; default 100000, use 0 for all remaining events",
    )
    parser.add_argument("--chunk-size", type=int, default=20_000)
    parser.add_argument("--mode", choices=("none", "local", "gradient"), default="local")
    parser.add_argument("--target-rate", type=float, default=100_000.0)
    parser.add_argument("--input-rate", type=float, default=40_000_000.0)
    parser.add_argument("--memory-size", type=int, default=5)
    parser.add_argument("--no-calibration", action="store_true")
    parser.add_argument("--calibration-start", type=int, default=0)
    parser.add_argument("--calibration-count", type=int, default=100_000)
    parser.add_argument("--initial-percentile", type=float, default=99.981)
    parser.add_argument("--step-percentile", type=float, default=99.977)
    parser.add_argument("--minimum-step", type=float, default=0.5)
    parser.add_argument(
        "--absolute-vbf-deta",
        action="store_true",
        help="interpret pair_deta as signed and trigger on abs(pair_deta)",
    )
    parser.add_argument("--rate-cost-weight", type=float, default=1.0)
    parser.add_argument(
        "--signal-cost-weight",
        type=float,
        help="default 1 with --signal-samples, otherwise 0",
    )
    parser.add_argument("--trigger-cost-weight", type=float, default=0.0)
    parser.add_argument("--event-cost-weight", type=float, default=0.0)
    parser.add_argument("--summary-json", type=Path)
    parser.add_argument("--history-json", type=Path)
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.start < 0 or args.calibration_start < 0:
        raise ValueError("start values must be nonnegative")
    if args.count < 0:
        raise ValueError("--count must be nonnegative")
    if args.chunk_size <= 0 or args.calibration_count <= 0:
        raise ValueError("chunk and calibration counts must be positive")
    if args.sample in args.signal_samples:
        raise ValueError("the background sample must not also be a signal sample")
    if len(set(args.signal_samples)) != len(args.signal_samples):
        raise ValueError("--signal-samples contains duplicates")


def _required_dataset_names(sample: str, sources: Iterable[str]) -> dict[str, str]:
    return {source: f"{sample}_{source}" for source in sources}


def _validate_datasets(
    h5: h5py.File,
    sample: str,
    sources: set[str],
) -> int:
    names = _required_dataset_names(sample, sources)
    missing = sorted(name for name in names.values() if name not in h5)
    if missing:
        raise KeyError(
            f"sample {sample!r} is missing required datasets: {', '.join(missing)}"
        )
    lengths = {name: int(h5[name].shape[0]) for name in names.values()}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"sample {sample!r} datasets have different lengths: {lengths}")
    return next(iter(lengths.values()))


def _read_chunk(
    h5: h5py.File,
    sample: str,
    sources: Iterable[str],
    start: int,
    stop: int,
) -> dict[str, np.ndarray]:
    return {source: h5[f"{sample}_{source}"][start:stop] for source in sources}


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_ready(value), indent=2) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    _validate_args(args)
    menu = default_trigger_menu(absolute_vbf_deta=args.absolute_vbf_deta)
    menu_sources = required_sources(menu)
    background_sources = set(menu_sources)
    if args.event_cost_weight:
        background_sources.add("njet")

    signal_weight = args.signal_cost_weight
    if signal_weight is None:
        signal_weight = 1.0 if args.signal_samples else 0.0
    weights = CostWeights(
        rate=args.rate_cost_weight,
        signal=signal_weight,
        trigger=args.trigger_cost_weight,
        event=args.event_cost_weight,
    )

    history: list[dict[str, Any]] = []
    calibration: dict[str, dict[str, float]] | None = None
    with h5py.File(args.hdf5, "r") as h5:
        background_length = _validate_datasets(h5, args.sample, background_sources)
        for sample in args.signal_samples:
            signal_length = _validate_datasets(h5, sample, menu_sources)
            if signal_length < background_length:
                raise ValueError(
                    f"signal sample {sample!r} has {signal_length} events, fewer than "
                    f"background sample {args.sample!r} with {background_length}"
                )

        if args.start > background_length:
            raise ValueError(f"--start {args.start} exceeds dataset length {background_length}")
        if not args.no_calibration:
            calibration_stop = min(
                background_length, args.calibration_start + args.calibration_count
            )
            if args.calibration_start >= calibration_stop:
                raise ValueError("calibration range is empty")
            calibration_chunk = _read_chunk(
                h5,
                args.sample,
                menu_sources,
                args.calibration_start,
                calibration_stop,
            )
            menu, calibration = suggest_initial_menu(
                calibration_chunk,
                menu,
                initial_percentile=args.initial_percentile,
                step_percentile=args.step_percentile,
                minimum_step=args.minimum_step,
            )

        controller = AdaptiveMenuController(
            menu,
            update_method=args.mode,
            target_rate=args.target_rate,
            input_rate=args.input_rate,
            memory_size=args.memory_size,
            weights=weights,
        )
        stop = (
            background_length
            if args.count == 0
            else min(background_length, args.start + args.count)
        )
        for chunk_index, begin in enumerate(range(args.start, stop, args.chunk_size)):
            end = min(begin + args.chunk_size, stop)
            background = _read_chunk(
                h5, args.sample, background_sources, begin, end
            )
            signals = {
                sample: _read_chunk(h5, sample, menu_sources, begin, end)
                for sample in args.signal_samples
            }
            result = controller.step(background, signals=signals or None)
            mean_npv = (
                float(np.mean(h5[f"{args.sample}_Npv"][begin:end]))
                if f"{args.sample}_Npv" in h5
                else None
            )
            history.append(
                {
                    "chunk": chunk_index,
                    "start": begin,
                    "stop": end,
                    "events": end - begin,
                    "mean_npv": mean_npv,
                    **result,
                }
            )

    total_rates = [entry["current"]["rates"]["total"] for entry in history]
    summary: dict[str, Any] = {
        "file": str(args.hdf5),
        "background_sample": args.sample,
        "signal_samples": list(args.signal_samples),
        "mode": args.mode,
        "menu_items": len(menu),
        "start": args.start,
        "stop": stop,
        "events": stop - args.start,
        "chunks": len(history),
        "input_rate_hz": args.input_rate,
        "target_rate_hz": args.target_rate,
        "weights": weights.__dict__,
        "calibration": calibration,
        "initial_cuts": {name: float(config["cut"]) for name, config in menu.items()},
        "final_cuts": controller.cuts,
        "legacy_fpga_cuts": {
            "ht_cut": controller.cuts["HT"],
            "ad_cut": controller.cuts["AD"],
        },
        "observed_total_rate_hz": {
            "minimum": min(total_rates) if total_rates else None,
            "mean": float(np.mean(total_rates)) if total_rates else None,
            "maximum": max(total_rates) if total_rates else None,
            "last": total_rates[-1] if total_rates else None,
        },
        "last_observation": history[-1]["current"] if history else None,
    }
    if args.history_json:
        _write_json(args.history_json, history)
    if args.summary_json:
        _write_json(args.summary_json, summary)
    return _json_ready(summary)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
