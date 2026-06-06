"""Tests for IRMP per-dimension computation."""
from modules.macro_political_risk.scoring.dimensions import (
    compute_dimension, compute_all_dimensions,
)
from modules.macro_political_risk.scoring.weights import DIMENSION_WEIGHTS

DATASET = {
    "DO": {"gdp_cagr_3y": 5.0, "inflation_gap": 1.0, "public_debt_gdp": 45.0,
           "fiscal_balance_gdp": -2.0, "reserves_import_months": 6.0},
    "CR": {"gdp_cagr_3y": 3.0, "inflation_gap": 3.0, "public_debt_gdp": 63.0,
           "fiscal_balance_gdp": -4.0, "reserves_import_months": 4.0},
    "PA": {"gdp_cagr_3y": 1.0, "inflation_gap": 5.0, "public_debt_gdp": 52.0,
           "fiscal_balance_gdp": -6.0, "reserves_import_months": 2.0},
}


def test_higher_growth_normalizes_to_top():
    res = compute_dimension("macro", "DO", DATASET)
    # DO has the max gdp_cagr_3y → that variable should normalize to 100
    assert res["variables"]["gdp_cagr_3y"]["normalized"] == 100.0


def test_risk_increasing_variable_is_inverted():
    res = compute_dimension("macro", "DO", DATASET)
    # DO has the LOWEST public_debt_gdp → inverted → best (100)
    assert res["variables"]["public_debt_gdp"]["inverted"] is True
    assert res["variables"]["public_debt_gdp"]["normalized"] == 100.0


def test_missing_variable_is_skipped():
    ds = {"DO": {"gdp_cagr_3y": 5.0}, "CR": {"gdp_cagr_3y": 3.0}}
    res = compute_dimension("macro", "DO", ds)
    # Only one variable present; others skipped, not interpolated
    assert set(res["variables"].keys()) == {"gdp_cagr_3y"}


def test_compute_all_dimensions_returns_five():
    dims = compute_all_dimensions("DO", DATASET)
    assert set(dims.keys()) == set(DIMENSION_WEIGHTS.keys())
