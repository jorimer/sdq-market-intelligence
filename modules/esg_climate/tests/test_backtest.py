"""Tests for the IRC backtest (Gate E) — Spearman + by-band monotonicity. Pure."""
from modules.esg_climate.validation.backtest import build_esg_backtest

# Higher IRC → lower climate mortality (the relationship we expect to validate).
_IRC = {"AAA": 80, "BBB": 70, "CCC": 55, "DDD": 45, "EEE": 30, "FFF": 20}
_MORT = {"AAA": 0.1, "BBB": 0.2, "CCC": 0.5, "DDD": 1.0, "EEE": 8.0, "FFF": 20.0}


def test_negative_correlation_and_monotonic():
    rep = build_esg_backtest(_IRC, _MORT)
    assert rep["computed"] and rep["n_countries"] == 6
    assert rep["spearman"] == -1.0           # perfectly inverse ranks
    assert rep["monotonic"] is True
    bands = {b["band"]: b["mean_climate_deaths_per_100k"] for b in rep["by_band"]}
    assert bands["Baja"] > bands["Moderada"] > bands["Alta"]   # resilience-low suffers more


def test_insufficient_data():
    rep = build_esg_backtest({"AAA": 50}, {"AAA": 1.0})
    assert rep["computed"] is False


def test_ci_present_when_computed():
    rep = build_esg_backtest(_IRC, _MORT)
    lo, hi = rep["spearman_ci"]
    # A bootstrap percentile CI is a valid ordered interval (the point estimate may
    # sit at/outside it for an extreme correlation, so we don't require containment).
    assert lo is not None and hi is not None and lo <= hi
