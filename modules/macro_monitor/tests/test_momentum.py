"""Tests for macro momentum scoring."""
from modules.macro_monitor.scoring.momentum import compute_series_momentum


def test_empty_series_is_insufficient():
    res = compute_series_momentum([])
    assert res["n_obs"] == 0
    assert res["trend"] == "insuficiente"
    assert res["change"] is None


def test_single_obs_is_insufficient():
    res = compute_series_momentum([("2025-Q1", 5.0)])
    assert res["n_obs"] == 1
    assert res["latest_value"] == 5.0
    assert res["trend"] == "insuficiente"


def test_two_obs_change_no_acceleration():
    res = compute_series_momentum([("2025-Q1", 4.0), ("2025-Q2", 5.0)])
    assert res["change"] == 1.0
    assert res["pct_change"] == 25.0
    assert res["acceleration"] is None
    assert res["trend"] == "estable"


def test_accelerating_trend():
    # changes: +1, +2 → acceleration +1 → acelerando
    res = compute_series_momentum([("Q1", 1.0), ("Q2", 2.0), ("Q3", 4.0)])
    assert res["change"] == 2.0
    assert res["acceleration"] == 1.0
    assert res["trend"] == "acelerando"


def test_decelerating_trend():
    # changes: +2, +1 → acceleration -1 → desacelerando
    res = compute_series_momentum([("Q1", 0.0), ("Q2", 2.0), ("Q3", 3.0)])
    assert res["acceleration"] == -1.0
    assert res["trend"] == "desacelerando"


def test_gaps_are_skipped_not_interpolated():
    res = compute_series_momentum([("Q1", 4.0), ("Q2", None), ("Q3", 6.0)])
    assert res["n_obs"] == 2
    assert res["latest_value"] == 6.0
    assert res["change"] == 2.0  # 6 - 4, the None is dropped


def test_volatility_and_uncertainty_band():
    res = compute_series_momentum([("Q1", 1.0), ("Q2", 2.0), ("Q3", 4.0), ("Q4", 7.0)])
    assert res["volatility"] is not None
    assert res["uncertainty_band"] is not None
    lo, hi = res["uncertainty_band"]
    assert lo <= hi


def test_continuity_prob_consistent_direction():
    # all positive changes → continuity prob 1.0
    res = compute_series_momentum([("Q1", 1.0), ("Q2", 2.0), ("Q3", 3.0), ("Q4", 4.0)])
    assert res["continuity_prob"] == 1.0


def test_pct_change_handles_zero_previous():
    res = compute_series_momentum([("Q1", 0.0), ("Q2", 3.0)])
    assert res["change"] == 3.0
    assert res["pct_change"] is None  # division by zero avoided
