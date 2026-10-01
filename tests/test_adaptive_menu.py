import numpy as np

from software.adaptive_menu import (
    AdaptiveMenuController,
    CostWeights,
    default_trigger_menu,
    evaluate_menu,
    match_npv_indices,
    required_sources,
    suggest_initial_menu,
)


def test_default_menu_has_22_items_and_extended_sources():
    menu = default_trigger_menu()
    assert len(menu) == 22
    assert menu["AD"]["cost"] == 4.0
    assert required_sources(menu) == {
        "jet_pt",
        "cjet_pt",
        "fjet_pt",
        "ht",
        "ht_central",
        "met",
        "met_central",
        "score02",
        "pair_mjj",
        "pair_min_pt",
        "pair_deta",
    }


def test_scalar_multijet_dijet_and_vbf_strict_comparisons():
    menu = {
        "scalar": {"type": "scalar", "source": "x", "cut": 5.0, "step": 1.0},
        "2j": {
            "type": "multijet",
            "source": "jets",
            "multiplicity": 2,
            "cut": 10.0,
            "step": 1.0,
        },
        "mjj": {"type": "dijet_mass", "cut": 100.0, "step": 10.0},
        "vbf": {
            "type": "vbf",
            "cut": 100.0,
            "step": 10.0,
            "pt_cut": 20.0,
            "deta_cut": 2.0,
            "absolute_deta": True,
        },
    }
    chunk = {
        "x": np.array([5.0, 6.0, 0.0]),
        "jets": np.array([[20.0, 10.0], [20.0, 11.0], [1.0, 0.0]]),
        "pair_mjj": np.array([[100.0, 90.0], [80.0, 101.0], [200.0, 0.0]]),
        "pair_min_pt": np.array([[30.0, 30.0], [30.0, 30.0], [10.0, 0.0]]),
        "pair_deta": np.array([[-3.0, 1.0], [1.0, -3.0], [4.0, 0.0]]),
    }
    result = evaluate_menu(chunk, menu)
    assert result["scalar"].tolist() == [0, 1, 0]
    assert result["2j"].tolist() == [0, 1, 0]
    assert result["mjj"].tolist() == [0, 1, 1]
    assert result["vbf"].tolist() == [0, 1, 0]
    assert result["total"].tolist() == [0, 1, 1]


def test_calibration_uses_real_percentiles_and_floors_zero_step():
    menu = {
        "x": {
            "type": "scalar",
            "source": "x",
            "cut": 0.0,
            "step": 1.0,
        }
    }
    calibrated, summary = suggest_initial_menu(
        {"x": np.ones(100)},
        menu,
        initial_percentile=99.0,
        step_percentile=98.0,
        minimum_step=0.5,
    )
    assert calibrated["x"]["cut"] == 1.0
    assert calibrated["x"]["step"] == 0.5
    assert summary["x"]["initial_percentile"] == 99.0
    assert summary["x"]["step_percentile"] == 98.0


def test_local_controller_moves_cut_toward_target_rate():
    menu = {
        "x": {
            "type": "scalar",
            "source": "x",
            "cut": 8.0,
            "step": 2.0,
            "min_cut": 0.0,
        }
    }
    controller = AdaptiveMenuController(
        menu,
        update_method="local",
        target_rate=50.0,
        input_rate=100.0,
        memory_size=1,
    )
    result = controller.step({"x": np.arange(10, dtype=float)})
    assert result["current"]["rates"]["total"] == 10.0
    assert result["new_cuts"]["x"] == 6.0
    assert result["best"]["rates"]["total"] == 30.0


def test_cost_weights_are_applied_instead_of_only_reported():
    menu = {
        "expensive": {
            "type": "scalar",
            "source": "x",
            "cut": 0.0,
            "step": 1.0,
            "cost": 4.0,
        }
    }
    controller = AdaptiveMenuController(
        menu,
        update_method="none",
        target_rate=100.0,
        input_rate=100.0,
        memory_size=1,
        weights=CostWeights(rate=1.0, trigger=2.0, event=3.0),
    )
    evaluation = controller.evaluate(
        {"x": np.ones(2), "njet": np.array([2.0, 4.0])}
    )
    assert evaluation["rate_cost"] == 0.0
    assert evaluation["trigger_cost"] == 4.0
    assert evaluation["event_cost"] == 3.0
    assert evaluation["cost"] == 17.0


def test_signal_cost_is_explicitly_offline_only():
    menu = {"x": {"type": "scalar", "source": "x", "cut": 0.0, "step": 1.0}}
    controller = AdaptiveMenuController(menu, weights=CostWeights(signal=1.0))
    with np.testing.assert_raises_regex(ValueError, "requires at least one signal"):
        controller.evaluate({"x": np.ones(2)})


def test_npv_matching_is_seeded_and_returns_original_indices():
    source = np.array([3, 1, 2, 2, 5])
    target = np.array([1, 2, 4, 5])
    first = match_npv_indices(target, source, seed=7)
    second = match_npv_indices(target, source, seed=7)
    assert np.array_equal(first, second)
    assert source[first].tolist()[0] == 1
    assert source[first].tolist()[1] == 2
    assert source[first].tolist()[2] in (3, 5)
    assert source[first].tolist()[3] == 5
