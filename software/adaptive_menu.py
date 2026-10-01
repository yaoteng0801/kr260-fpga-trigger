"""Adaptive multi-item trigger-menu model for offline and PS-side studies.

This module deliberately does not replace the deployed two-item FPGA data
path.  It provides a deterministic NumPy reference for the extended trigger
menu and the slow control loop that may eventually update PL thresholds
between event chunks.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np


Menu = dict[str, dict[str, Any]]
Chunk = Mapping[str, np.ndarray]


def default_trigger_menu(*, absolute_vbf_deta: bool = False) -> Menu:
    """Return a fresh copy of the 22-item menu from the study notebook."""

    def multijet(source: str, multiplicity: int, cut: float, step: float) -> dict[str, Any]:
        return {
            "type": "multijet",
            "source": source,
            "multiplicity": multiplicity,
            "cut": cut,
            "step": step,
            "cost": 1.0,
            "min_cut": 0.0,
        }

    def scalar(source: str, cut: float, step: float, cost: float = 1.0) -> dict[str, Any]:
        return {
            "type": "scalar",
            "source": source,
            "cut": cut,
            "step": step,
            "cost": cost,
            "min_cut": 0.0,
        }

    return {
        "1j": multijet("jet_pt", 1, 400.0, 20.0),
        "3j": multijet("jet_pt", 3, 200.0, 20.0),
        "4j": multijet("jet_pt", 4, 160.0, 20.0),
        "5j": multijet("jet_pt", 5, 120.0, 20.0),
        "6j": multijet("jet_pt", 6, 80.0, 10.0),
        "1j_central": multijet("cjet_pt", 1, 400.0, 20.0),
        "3j_central": multijet("cjet_pt", 3, 200.0, 20.0),
        "4j_central": multijet("cjet_pt", 4, 160.0, 20.0),
        "5j_central": multijet("cjet_pt", 5, 120.0, 20.0),
        "6j_central": multijet("cjet_pt", 6, 80.0, 10.0),
        "1j_forward": multijet("fjet_pt", 1, 200.0, 20.0),
        "3j_forward": multijet("fjet_pt", 3, 200.0, 20.0),
        "4j_forward": multijet("fjet_pt", 4, 160.0, 20.0),
        "5j_forward": multijet("fjet_pt", 5, 120.0, 20.0),
        "6j_forward": multijet("fjet_pt", 6, 80.0, 10.0),
        "HT": scalar("ht", 300.0, 20.0),
        "HT_central": scalar("ht_central", 230.0, 20.0),
        "MET": scalar("met", 200.0, 20.0),
        "MET_central": scalar("met_central", 180.0, 20.0),
        "AD": scalar("score02", 300.0, 20.0, cost=4.0),
        "dijet_mass": {
            "type": "dijet_mass",
            "cut": 1000.0,
            "step": 50.0,
            "cost": 1.0,
            "min_cut": 0.0,
        },
        "VBF": {
            "type": "vbf",
            "pt_cut": 50.0,
            "deta_cut": 2.0,
            "absolute_deta": absolute_vbf_deta,
            "cut": 1000.0,
            "step": 50.0,
            "cost": 1.0,
            "min_cut": 0.0,
        },
    }


def validate_menu(menu: Mapping[str, Mapping[str, Any]]) -> None:
    """Validate menu structure before any expensive event processing."""

    if not menu:
        raise ValueError("trigger menu must not be empty")
    if "total" in menu:
        raise ValueError("'total' is reserved for the combined menu decision")

    supported = {"scalar", "multijet", "dijet_mass", "vbf"}
    for name, config in menu.items():
        trigger_type = config.get("type")
        if trigger_type not in supported:
            raise ValueError(f"unsupported trigger type {trigger_type!r} for {name!r}")
        for field in ("cut", "step"):
            value = float(config[field])
            if not np.isfinite(value):
                raise ValueError(f"{name}.{field} must be finite")
        if float(config["step"]) <= 0:
            raise ValueError(f"{name}.step must be positive")
        if trigger_type in {"scalar", "multijet"} and not config.get("source"):
            raise ValueError(f"{name}.source is required")
        if trigger_type == "multijet" and int(config.get("multiplicity", 0)) <= 0:
            raise ValueError(f"{name}.multiplicity must be positive")
        if trigger_type == "vbf":
            for field in ("pt_cut", "deta_cut"):
                if field not in config:
                    raise ValueError(f"{name}.{field} is required")


def required_sources(menu: Mapping[str, Mapping[str, Any]]) -> set[str]:
    """Return HDF5 source suffixes required to evaluate ``menu``."""

    validate_menu(menu)
    sources: set[str] = set()
    for config in menu.values():
        trigger_type = config["type"]
        if trigger_type in {"scalar", "multijet"}:
            sources.add(str(config["source"]))
        elif trigger_type == "dijet_mass":
            sources.add("pair_mjj")
        elif trigger_type == "vbf":
            sources.update(("pair_mjj", "pair_min_pt", "pair_deta"))
    return sources


def _event_count(chunk: Chunk) -> int:
    if not chunk:
        raise ValueError("event chunk must not be empty")
    lengths = {name: np.asarray(values).shape[0] for name, values in chunk.items()}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"chunk arrays have different event counts: {lengths}")
    return next(iter(lengths.values()))


def _pair_arrays(chunk: Chunk) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mjj = np.asarray(chunk["pair_mjj"])
    min_pt = np.asarray(chunk["pair_min_pt"])
    deta = np.asarray(chunk["pair_deta"])
    if mjj.ndim != 2 or min_pt.shape != mjj.shape or deta.shape != mjj.shape:
        raise ValueError("pair_mjj, pair_min_pt, and pair_deta must be equal 2-D arrays")
    return mjj, min_pt, deta


def item_values(chunk: Chunk, config: Mapping[str, Any]) -> np.ndarray:
    """Return one scalar trigger variable per event for a menu item."""

    trigger_type = config["type"]
    if trigger_type == "scalar":
        values = np.asarray(chunk[str(config["source"])])
        if values.ndim != 1:
            raise ValueError(f"scalar source {config['source']!r} must be one-dimensional")
        return values

    if trigger_type == "multijet":
        jets = np.asarray(chunk[str(config["source"])])
        multiplicity = int(config["multiplicity"])
        if jets.ndim != 2 or jets.shape[1] < multiplicity:
            raise ValueError(
                f"multijet source {config['source']!r} needs at least {multiplicity} columns"
            )
        return jets[:, multiplicity - 1]

    if trigger_type == "dijet_mass":
        mjj = np.asarray(chunk["pair_mjj"])
        if mjj.ndim != 2 or mjj.shape[1] == 0:
            raise ValueError("pair_mjj must be a nonempty two-dimensional array")
        return np.max(mjj, axis=1)

    if trigger_type == "vbf":
        mjj, min_pt, deta = _pair_arrays(chunk)
        if mjj.shape[1] == 0:
            raise ValueError("VBF evaluation requires at least one pair column")
        deta_value = np.abs(deta) if config.get("absolute_deta", False) else deta
        valid = (min_pt > float(config["pt_cut"])) & (
            deta_value > float(config["deta_cut"])
        )
        return np.max(np.where(valid, mjj, 0.0), axis=1)

    raise ValueError(f"unknown trigger type {trigger_type!r}")


def evaluate_menu(
    chunk: Chunk,
    menu: Mapping[str, Mapping[str, Any]],
    cuts: Mapping[str, float] | None = None,
) -> dict[str, np.ndarray]:
    """Evaluate every item with strict ``>`` semantics and form their OR."""

    validate_menu(menu)
    event_count = _event_count(chunk)
    decisions: dict[str, np.ndarray] = {}
    for name, config in menu.items():
        cut = float(config["cut"] if cuts is None else cuts[name])
        values = item_values(chunk, config)
        if values.shape[0] != event_count:
            raise ValueError(f"item {name!r} returned the wrong event count")
        decisions[name] = (values > cut).astype(np.uint8)
    decisions["total"] = np.any(np.stack(list(decisions.values()), axis=0), axis=0).astype(
        np.uint8
    )
    return decisions


def calculate_rates(
    decisions: Mapping[str, np.ndarray], input_rate: float = 40_000_000.0
) -> dict[str, float]:
    if input_rate <= 0:
        raise ValueError("input_rate must be positive")
    return {
        name: float(np.mean(np.asarray(values, dtype=bool)) * input_rate)
        for name, values in decisions.items()
    }


def suggest_initial_menu(
    background: Chunk,
    menu: Mapping[str, Mapping[str, Any]],
    *,
    initial_percentile: float = 99.981,
    step_percentile: float = 99.977,
    minimum_step: float = 0.5,
) -> tuple[Menu, dict[str, dict[str, float]]]:
    """Calibrate cuts and positive finite-difference steps from background."""

    if not 0 <= step_percentile < initial_percentile <= 100:
        raise ValueError("percentiles must satisfy 0 <= step < initial <= 100")
    if minimum_step <= 0:
        raise ValueError("minimum_step must be positive")
    _event_count(background)

    calibrated = deepcopy(dict(menu))
    summary: dict[str, dict[str, float]] = {}
    for name, config in calibrated.items():
        values = np.asarray(item_values(background, config), dtype=np.float64)
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            raise ValueError(f"item {name!r} has no finite calibration values")
        initial = float(np.percentile(finite, initial_percentile))
        lower = float(np.percentile(finite, step_percentile))
        step = max(initial - lower, float(config.get("minimum_step", minimum_step)))
        config["cut"] = initial
        config["step"] = step
        summary[name] = {
            "initial_cut": initial,
            "step": step,
            "initial_percentile": initial_percentile,
            "step_percentile": step_percentile,
        }
    validate_menu(calibrated)
    return calibrated, summary


def match_npv_indices(
    target_npvs: np.ndarray,
    source_npvs: np.ndarray,
    *,
    seed: int = 0,
) -> np.ndarray:
    """Match source events to target NPV values with deterministic resampling.

    Exact matches are sampled with replacement.  If an exact NPV is absent,
    the closest available NPV is used.  Returned indices address the original
    source order.
    """

    target = np.asarray(target_npvs)
    source = np.asarray(source_npvs)
    if target.ndim != 1 or source.ndim != 1 or source.size == 0:
        raise ValueError("target_npvs and nonempty source_npvs must be one-dimensional")
    rng = np.random.default_rng(seed)
    order = np.argsort(source, kind="stable")
    sorted_npvs = source[order]
    right = np.searchsorted(sorted_npvs, target, side="left")
    left = np.clip(right - 1, 0, sorted_npvs.size - 1)
    right = np.clip(right, 0, sorted_npvs.size - 1)
    selected = np.where(
        np.abs(sorted_npvs[left] - target) <= np.abs(sorted_npvs[right] - target),
        left,
        right,
    )
    exact_left = np.searchsorted(sorted_npvs, target, side="left")
    exact_right = np.searchsorted(sorted_npvs, target, side="right")
    exact = exact_right > exact_left
    if np.any(exact):
        widths = exact_right[exact] - exact_left[exact]
        offsets = (rng.random(np.count_nonzero(exact)) * widths).astype(np.int64)
        selected[exact] = exact_left[exact] + offsets
    return order[selected]


@dataclass(frozen=True)
class CostWeights:
    """Weights for explicit controller objectives.

    Signal cost defaults to zero so the controller is safe to use without
    truth-labelled online signal samples.  Offline studies can set it to one.
    """

    rate: float = 1.0
    signal: float = 0.0
    trigger: float = 0.0
    event: float = 0.0

    def __post_init__(self) -> None:
        if any(value < 0 or not np.isfinite(value) for value in self.__dict__.values()):
            raise ValueError("cost weights must be finite and nonnegative")


class AdaptiveMenuController:
    """Chunk-level fixed, coordinate-search, or gradient menu controller."""

    METHODS = {"none", "local", "gradient"}

    def __init__(
        self,
        menu: Mapping[str, Mapping[str, Any]],
        *,
        update_method: str = "local",
        target_rate: float = 100_000.0,
        input_rate: float = 40_000_000.0,
        memory_size: int = 5,
        weights: CostWeights | None = None,
        rate_tolerance_fraction: float = 0.05,
        efficiency_scale: float = 0.05,
        gradient_gains: Sequence[float] = (0.0, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0),
    ) -> None:
        validate_menu(menu)
        if update_method not in self.METHODS:
            raise ValueError(f"update_method must be one of {sorted(self.METHODS)}")
        if target_rate <= 0 or input_rate <= 0:
            raise ValueError("target_rate and input_rate must be positive")
        if memory_size <= 0:
            raise ValueError("memory_size must be positive")
        if rate_tolerance_fraction <= 0 or efficiency_scale <= 0:
            raise ValueError("cost scales must be positive")
        if not gradient_gains or any(gain < 0 for gain in gradient_gains):
            raise ValueError("gradient_gains must be nonempty and nonnegative")

        self.menu = deepcopy(dict(menu))
        self.update_method = update_method
        self.target_rate = float(target_rate)
        self.input_rate = float(input_rate)
        self.memory_size = int(memory_size)
        self.weights = weights or CostWeights()
        self.rate_tolerance_fraction = float(rate_tolerance_fraction)
        self.efficiency_scale = float(efficiency_scale)
        self.gradient_gains = tuple(float(value) for value in gradient_gains)
        self.cuts = {name: float(config["cut"]) for name, config in self.menu.items()}
        self.steps = {name: float(config["step"]) for name, config in self.menu.items()}
        self._memory = {
            name: deque(maxlen=self.memory_size)
            for name in self.menu
        }
        self.history: list[dict[str, Any]] = []

    def _sanitize_cut(self, name: str, value: float) -> float:
        config = self.menu[name]
        low = float(config.get("min_cut", 0.0))
        high = float(config.get("max_cut", np.inf))
        return float(np.clip(value, low, high))

    def _trigger_cost(self, decisions: Mapping[str, np.ndarray]) -> float:
        accepted = np.asarray(decisions["total"], dtype=bool)
        if not np.any(accepted):
            return 0.0
        per_event = np.zeros(accepted.size, dtype=np.float64)
        for name, config in self.menu.items():
            passed = np.asarray(decisions[name], dtype=bool)
            per_event[passed] = np.maximum(per_event[passed], float(config.get("cost", 1.0)))
        return float(np.mean(per_event[accepted]))

    def evaluate(
        self,
        background: Chunk,
        *,
        cuts: Mapping[str, float] | None = None,
        signals: Mapping[str, Chunk] | None = None,
    ) -> dict[str, Any]:
        active_cuts = self.cuts if cuts is None else cuts
        decisions = evaluate_menu(background, self.menu, active_cuts)
        rates = calculate_rates(decisions, self.input_rate)
        rate_cost = abs(rates["total"] - self.target_rate) / (
            self.target_rate * self.rate_tolerance_fraction
        )

        efficiencies: dict[str, dict[str, float]] = {}
        if signals:
            for sample, chunk in signals.items():
                sample_decisions = evaluate_menu(chunk, self.menu, active_cuts)
                efficiencies[sample] = {
                    name: float(np.mean(value)) for name, value in sample_decisions.items()
                }
        total_efficiency = (
            float(np.mean([sample["total"] for sample in efficiencies.values()]))
            if efficiencies
            else None
        )
        if self.weights.signal and total_efficiency is None:
            raise ValueError("a nonzero signal cost weight requires at least one signal chunk")
        signal_cost = (
            (1.0 - total_efficiency) / self.efficiency_scale
            if total_efficiency is not None
            else None
        )

        trigger_cost = self._trigger_cost(decisions)
        accepted = np.asarray(decisions["total"], dtype=bool)
        if self.weights.event and "njet" not in background:
            raise ValueError("a nonzero event cost weight requires background['njet']")
        event_cost = (
            float(np.mean(np.asarray(background["njet"])[accepted]))
            if "njet" in background and np.any(accepted)
            else 0.0
        )
        cost = (
            self.weights.rate * rate_cost
            + self.weights.trigger * trigger_cost
            + self.weights.event * event_cost
            + self.weights.signal * (signal_cost or 0.0)
        )
        return {
            "cost": float(cost),
            "rate_cost": float(rate_cost),
            "signal_cost": None if signal_cost is None else float(signal_cost),
            "trigger_cost": trigger_cost,
            "event_cost": event_cost,
            "total_efficiency": total_efficiency,
            "efficiencies": efficiencies,
            "rates": rates,
        }

    def _local_update(self, background: Chunk, signals: Mapping[str, Chunk] | None) -> dict[str, Any]:
        best_cuts = self.cuts.copy()
        best = self.evaluate(background, cuts=best_cuts, signals=signals)
        for name in self.menu:
            for direction in (-1.0, 1.0):
                candidate = self.cuts.copy()
                candidate[name] = self._sanitize_cut(
                    name, self.cuts[name] + direction * self.steps[name]
                )
                if candidate[name] == self.cuts[name]:
                    continue
                evaluation = self.evaluate(background, cuts=candidate, signals=signals)
                if evaluation["cost"] < best["cost"]:
                    best_cuts = candidate
                    best = evaluation
        return {"cuts": best_cuts, "evaluation": best, "gradients": None, "best_gain": None}

    def _gradient_update(
        self, background: Chunk, signals: Mapping[str, Chunk] | None
    ) -> dict[str, Any]:
        scaled: dict[str, float] = {}
        gradients: dict[str, float] = {}
        for name in self.menu:
            minus = self.cuts.copy()
            plus = self.cuts.copy()
            minus[name] = self._sanitize_cut(name, self.cuts[name] - self.steps[name])
            plus[name] = self._sanitize_cut(name, self.cuts[name] + self.steps[name])
            span = plus[name] - minus[name]
            if span == 0:
                gradients[name] = 0.0
                scaled[name] = 0.0
                continue
            minus_cost = self.evaluate(background, cuts=minus, signals=signals)["cost"]
            plus_cost = self.evaluate(background, cuts=plus, signals=signals)["cost"]
            gradients[name] = (plus_cost - minus_cost) / span
            scaled[name] = gradients[name] * self.steps[name]

        norm = float(np.linalg.norm(np.fromiter(scaled.values(), dtype=np.float64)))
        direction = {
            name: (value / norm if norm else 0.0) for name, value in scaled.items()
        }
        best_cuts = self.cuts.copy()
        best = self.evaluate(background, cuts=best_cuts, signals=signals)
        best_gain = 0.0
        for gain in self.gradient_gains:
            candidate = {
                name: self._sanitize_cut(
                    name, self.cuts[name] - gain * direction[name] * self.steps[name]
                )
                for name in self.menu
            }
            evaluation = self.evaluate(background, cuts=candidate, signals=signals)
            if evaluation["cost"] < best["cost"]:
                best_cuts = candidate
                best = evaluation
                best_gain = gain
        return {
            "cuts": best_cuts,
            "evaluation": best,
            "gradients": gradients,
            "best_gain": best_gain,
        }

    def _smooth(self, proposed: Mapping[str, float]) -> dict[str, float]:
        smoothed: dict[str, float] = {}
        for name, value in proposed.items():
            self._memory[name].append(float(value))
            output = value if len(self._memory[name]) < self.memory_size else np.mean(self._memory[name])
            smoothed[name] = self._sanitize_cut(name, float(output))
        return smoothed

    def step(
        self,
        background: Chunk,
        *,
        signals: Mapping[str, Chunk] | None = None,
    ) -> dict[str, Any]:
        """Evaluate the current cuts and choose cuts for the next chunk."""

        old_cuts = self.cuts.copy()
        current = self.evaluate(background, signals=signals)
        if self.update_method == "none":
            update = {
                "cuts": old_cuts.copy(),
                "evaluation": current,
                "gradients": None,
                "best_gain": None,
            }
        elif self.update_method == "local":
            update = self._local_update(background, signals)
        else:
            update = self._gradient_update(background, signals)

        proposed = update["cuts"].copy()
        self.cuts = self._smooth(proposed)
        result = {
            "old_cuts": old_cuts,
            "proposed_cuts": proposed,
            "new_cuts": self.cuts.copy(),
            "current": current,
            "best": update["evaluation"],
            "gradients": update["gradients"],
            "best_gain": update["best_gain"],
        }
        self.history.append(result)
        return result
