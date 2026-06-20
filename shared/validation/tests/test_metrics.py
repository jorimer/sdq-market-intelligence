"""Tests for the shared backtest metrics — focus on mean_ic_with_t (Gate-E fix)."""
import pytest

from shared.validation.metrics import (
    deterioration_rate_by_tier,
    gini,
    gini_bootstrap_ci,
    mean_ic_with_t,
    spearman,
    spearman_bootstrap_ci,
)


# ── mean_ic_with_t (the panel inference fix) ──────────────────────
def test_mean_ic_with_t_known_series():
    out = mean_ic_with_t([0.2, 0.4, 0.6])
    assert out["mean_ic"] == 0.4
    assert out["n_years"] == 3
    assert out["sd"] == pytest.approx(0.2, abs=1e-9)
    # se = 0.2/sqrt(3) ≈ 0.11547 → t = 0.4/0.11547 ≈ 3.464
    assert out["t_stat"] == pytest.approx(3.464, abs=0.01)
    # t_{0.975, df=2} ≈ 4.303 → half ≈ 0.497 → CI crosses zero (wide with k=3)
    assert out["ci_lo"] == pytest.approx(-0.097, abs=0.01)
    assert out["ci_hi"] == pytest.approx(0.897, abs=0.01)


def test_mean_ic_with_t_detects_consistent_signal():
    out = mean_ic_with_t([0.8, 0.85, 0.9, 0.82])
    assert out["mean_ic"] > 0.8
    assert out["ci_lo"] > 0          # CI excludes zero → signal detected
    assert out["t_stat"] > 0


def test_mean_ic_with_t_needs_at_least_two_years():
    assert mean_ic_with_t([0.5]) is None
    assert mean_ic_with_t([]) is None


def test_mean_ic_with_t_zero_variance_t_undefined():
    out = mean_ic_with_t([0.3, 0.3, 0.3])
    assert out["sd"] == 0.0
    assert out["t_stat"] is None          # undefined, not a crash
    assert out["ci_lo"] == out["ci_hi"] == 0.3


def test_mean_ic_with_t_wider_than_pooled_would_be():
    # the whole point: a noisy 6-year series gives a CI that comfortably spans zero
    out = mean_ic_with_t([-0.4, 0.6, -0.2, 0.3, 0.0, -0.1])
    assert out["ci_lo"] < 0 < out["ci_hi"]


# ── smoke for the reused metrics (keep file coverage healthy) ─────
def test_spearman_basic():
    assert spearman([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 2], [1, 2]) is None          # n < 3


def test_spearman_bootstrap_ci_shape():
    rho, lo, hi = spearman_bootstrap_ci([1, 2, 3, 4, 5], [2, 1, 4, 3, 5])
    assert rho is not None and lo is not None and hi is not None
    assert lo <= rho <= hi


def test_gini_perfect_and_random():
    assert gini([0.1, 0.2, 0.9, 0.8], [1, 1, 0, 0]) == pytest.approx(1.0)
    assert gini([0.5, 0.5], [1, 1]) is None          # one class absent


def test_gini_bootstrap_ci_shape():
    g, lo, hi = gini_bootstrap_ci([0.1, 0.3, 0.7, 0.9, 0.2, 0.8], [1, 1, 0, 0, 1, 0], n_boot=200)
    assert g is not None and lo is not None and hi is not None
    assert lo <= g <= hi


def test_spearman_bootstrap_ci_none_when_undefined():
    assert spearman_bootstrap_ci([1, 2], [1, 2]) == (None, None, None)   # n < 3 → base None


def test_deterioration_rate_by_tier_monotonic():
    rows, monotonic = deterioration_rate_by_tier(
        ["A", "A", "B", "B"], [0, 0, 1, 1], ["A", "B"])
    assert monotonic is True
    assert rows[0]["tier"] == "A" and rows[0]["rate"] == 0.0
    assert rows[1]["tier"] == "B" and rows[1]["rate"] == 1.0
