#!/usr/bin/env python3
"""Stream an extended 22-item HDF5 trigger menu through the KR260 V2 PL."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable, Mapping

import h5py
import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from software.adaptive_menu import (  # noqa: E402
    AdaptiveMenuController,
    CostWeights,
    default_trigger_menu,
    required_sources,
)
from software.hw_access import LinuxDmaSession, PynqDmaSession  # noqa: E402
from software.hw_access_v2 import (  # noqa: E402
    TriggerV2RegisterLayout,
    TriggerV2Registers,
    configure_v2_register_map,
    v2_identity,
)
from software.trigger_v2_format import (  # noqa: E402
    FRAMING_ERROR_BIT,
    ITEM_NAMES,
    KEEP_ERROR_BIT,
    N_ITEMS,
    WORDS_PER_EVENT,
    feature_matrix,
    golden_results_packed,
    pack_features,
    quantize_cuts,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hdf5", type=Path, help="extended trigger-food HDF5 file")
    parser.add_argument("--sample", default="bkg")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, help="events to process; default through file end")
    parser.add_argument("--chunk-size", type=int, default=20_000)
    parser.add_argument("--cuts-json", type=Path, help="adaptive summary or direct cut map")
    parser.add_argument(
        "--cut",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="override one floating threshold; may be repeated",
    )
    parser.add_argument("--absolute-vbf-deta", action="store_true")
    parser.add_argument(
        "--adaptive-mode",
        choices=("none", "local", "gradient"),
        default="none",
        help="PS rate-only threshold update applied between FPGA chunks",
    )
    parser.add_argument("--target-rate", type=float, default=100_000.0)
    parser.add_argument("--input-rate", type=float, default=40_000_000.0)
    parser.add_argument("--memory-size", type=int, default=5)
    parser.add_argument("--software-only", action="store_true")
    parser.add_argument("--backend", choices=("uio", "pynq"), default="uio")
    parser.add_argument("--bitstream", type=Path)
    parser.add_argument("--pynq-buffer-size", type=int, default=4 * 1024 * 1024)
    parser.add_argument("--pynq-loader", choices=("bitstream", "overlay"), default="bitstream")
    parser.add_argument("--pynq-clock-mhz", type=float, default=100.0)
    parser.add_argument("--dma-uio-name", default="kr260-trigger-v2-dma")
    parser.add_argument("--trigger-uio-name", default="kr260-axis-trigger-v2")
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
    if args.pynq_buffer_size <= 0:
        raise ValueError("--pynq-buffer-size must be positive")
    if not args.software_only and args.backend == "pynq" and args.bitstream is None:
        raise ValueError("--bitstream is required with --backend pynq")


def _load_cut_file(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("cuts JSON must contain an object")
    for key in ("final_cuts", "cuts", "initial_cuts"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def _parse_cut_overrides(values: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid --cut {value!r}; expected NAME=VALUE")
        name, raw = value.split("=", 1)
        if name not in ITEM_NAMES:
            raise ValueError(f"unknown V2 trigger item {name!r}")
        number = float(raw)
        if not np.isfinite(number) or number < 0:
            raise ValueError(f"cut {name!r} must be finite and nonnegative")
        result[name] = number
    return result


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


def run(args: argparse.Namespace) -> dict[str, Any]:
    _validate_args(args)
    menu = default_trigger_menu(absolute_vbf_deta=args.absolute_vbf_deta)
    cuts = {name: float(config["cut"]) for name, config in menu.items()}
    if args.cuts_json:
        loaded = _load_cut_file(args.cuts_json)
        missing = [name for name in ITEM_NAMES if name not in loaded]
        if missing:
            raise KeyError(f"cuts JSON is missing V2 items: {missing}")
        cuts.update({name: float(loaded[name]) for name in ITEM_NAMES})
    cuts.update(_parse_cut_overrides(args.cut))
    for name, value in cuts.items():
        if not np.isfinite(value) or value < 0:
            raise ValueError(f"cut {name!r} must be finite and nonnegative")
        menu[name]["cut"] = value

    controller = None
    if args.adaptive_mode != "none":
        controller = AdaptiveMenuController(
            deepcopy(menu),
            update_method=args.adaptive_mode,
            target_rate=args.target_rate,
            input_rate=args.input_rate,
            memory_size=args.memory_size,
            weights=CostWeights(rate=1.0),
        )

    sources = required_sources(menu)
    cuts_q = quantize_cuts(cuts, menu)
    initial_cuts = cuts.copy()
    initial_cuts_q = cuts_q.copy()
    configure_hardware: Callable[[np.ndarray], None] | None = None
    total_events = 0
    chunks = 0
    total_hdf5_s = 0.0
    total_pack_s = 0.0
    total_dma_s = 0.0
    mismatch_count = 0
    mismatch_indices: list[int] = []
    keep_error_count = 0
    framing_error_count = 0
    item_pass_counts = np.zeros(N_ITEMS, dtype=np.int64)
    cut_updates: list[dict[str, Any]] = []

    with ExitStack() as stack:
        h5 = stack.enter_context(h5py.File(args.hdf5, "r"))
        dataset_names = {source: f"{args.sample}_{source}" for source in sources}
        missing = sorted(name for name in dataset_names.values() if name not in h5)
        if missing:
            raise KeyError(f"missing V2 datasets: {missing}")
        lengths = {name: int(h5[name].shape[0]) for name in dataset_names.values()}
        if len(set(lengths.values())) != 1:
            raise ValueError(f"V2 datasets have different event counts: {lengths}")
        dataset_length = next(iter(lengths.values()))
        if args.start > dataset_length:
            raise ValueError(f"--start {args.start} exceeds dataset length {dataset_length}")
        stop = (
            dataset_length
            if args.count is None
            else min(dataset_length, args.start + args.count)
        )

        dma = None
        hardware_backend = "software"
        trigger_version = None
        trigger_capabilities = None
        if not args.software_only:
            hardware_backend = args.backend
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
                    raise RuntimeError("PYNQ session did not create trigger MMIO")
                configure_hardware = lambda values: configure_v2_register_map(
                    dma.trigger_regs, values
                )
                trigger_version, trigger_capabilities = v2_identity(dma.trigger_regs)
            else:
                dma = stack.enter_context(
                    LinuxDmaSession(
                        dma_uio_name=args.dma_uio_name,
                        input_device=args.input_buffer,
                        output_device=args.output_buffer,
                    )
                )
                trigger = stack.enter_context(TriggerV2Registers(args.trigger_uio_name))
                configure_hardware = trigger.configure
                trigger_version, trigger_capabilities = trigger.identity()

            if trigger_version != TriggerV2RegisterLayout.EXPECTED_VERSION:
                raise RuntimeError(
                    f"wrong trigger version 0x{trigger_version:08x}; "
                    f"expected V2 0x{TriggerV2RegisterLayout.EXPECTED_VERSION:08x}"
                )
            configure_hardware(cuts_q)

        for begin in range(args.start, stop, args.chunk_size):
            end = min(begin + args.chunk_size, stop)
            read_start = time.perf_counter()
            chunk = {
                source: h5[dataset_name][begin:end]
                for source, dataset_name in dataset_names.items()
            }
            total_hdf5_s += time.perf_counter() - read_start

            pack_start = time.perf_counter()
            features = feature_matrix(chunk, menu)
            packed = pack_features(features)
            expected = golden_results_packed(packed, cuts_q)
            total_pack_s += time.perf_counter() - pack_start
            event_count = end - begin
            if packed.size != event_count * WORDS_PER_EVENT:
                raise RuntimeError("V2 packer produced an invalid event length")

            if dma is None:
                actual = expected.copy()
                dma_elapsed = 0.0
            else:
                actual, dma_elapsed = dma.transfer_array(
                    packed,
                    np.dtype("<u4"),
                    event_count,
                    timeout_s=args.timeout,
                )
            total_dma_s += dma_elapsed

            keep_error_count += int(np.count_nonzero(actual & KEEP_ERROR_BIT))
            framing_error_count += int(np.count_nonzero(actual & FRAMING_ERROR_BIT))
            for index in range(N_ITEMS):
                item_pass_counts[index] += int(
                    np.count_nonzero(actual & np.uint32(1 << index))
                )
            unequal = np.flatnonzero(actual != expected)
            mismatch_count += int(unequal.size)
            remaining = max(0, args.max_mismatch_indices - len(mismatch_indices))
            mismatch_indices.extend((begin + unequal[:remaining]).tolist())
            total_events += event_count
            chunks += 1

            if controller is not None:
                update = controller.step(chunk)
                cuts = update["new_cuts"]
                cuts_q = quantize_cuts(cuts, menu)
                if configure_hardware is not None and end < stop:
                    configure_hardware(cuts_q)
                cut_updates.append(
                    {
                        "start": begin,
                        "stop": end,
                        "observed_total_rate_hz": update["current"]["rates"]["total"],
                        "new_cuts": cuts.copy(),
                        "new_cuts_quantized": cuts_q.copy(),
                        "best_gain": update["best_gain"],
                    }
                )

    input_bytes = total_events * WORDS_PER_EVENT * 8
    output_bytes = total_events * 4
    report: dict[str, Any] = {
        "file": str(args.hdf5),
        "sample": args.sample,
        "start": args.start,
        "stop": stop,
        "events": total_events,
        "chunks": chunks,
        "menu_items": N_ITEMS,
        "words_per_event": WORDS_PER_EVENT,
        "feature_scale": 256.0,
        "adaptive_mode": args.adaptive_mode,
        "initial_cuts": initial_cuts,
        "initial_cuts_quantized": initial_cuts_q,
        "final_cuts": cuts,
        "final_cuts_quantized": cuts_q,
        "cut_updates": cut_updates,
        "hdf5_read_seconds": total_hdf5_s,
        "feature_pack_seconds": total_pack_s,
        "dma_seconds": total_dma_s,
        "dma_bytes_bidirectional": input_bytes + output_bytes,
        "dma_throughput_MBps": (
            (input_bytes + output_bytes) / total_dma_s / 1e6 if total_dma_s else None
        ),
        "trigger_throughput_events_per_second": (
            total_events / total_dma_s if total_dma_s else None
        ),
        "item_pass_counts": {
            name: int(item_pass_counts[index]) for index, name in enumerate(ITEM_NAMES)
        },
        "mismatches": mismatch_count,
        "mismatch_indices": mismatch_indices,
        "keep_errors": keep_error_count,
        "framing_errors": framing_error_count,
        "hardware_executed": not args.software_only,
        "hardware_backend": hardware_backend,
        "trigger_version": trigger_version,
        "trigger_capabilities": trigger_capabilities,
        "bitstream": str(args.bitstream) if args.bitstream else None,
    }
    ready = _json_ready(report)
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(ready, indent=2) + "\n", encoding="utf-8")
    return ready


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return (
        0
        if report["mismatches"] == 0
        and report["keep_errors"] == 0
        and report["framing_errors"] == 0
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
