"""Tests for the IRMP scoring engine."""
import pytest
from modules.macro_political_risk.scoring.engine import run_irmp
from modules.macro_political_risk.scoring.weights import DIMENSION_WEIGHTS

DATASET = {
    "DO": {"gdp_cagr_3y": 5.0, "public_debt_gdp": 45.0, "wgi_rule_of_law": 55.0,
           "fx_volatility": 3.0, "news_sentiment": 20.0, "discretion": 30.0},
    "CR": {"gdp_cagr_3y": 3.0, "public_debt_gdp": 63.0, "wgi_rule_of_law": 65.0,
           "fx_volatility": 5.0, "news_sentiment": 10.0, "discretion": 40.0},
    "PA": {"gdp_cagr_3y": 1.0, "public_debt_gdp": 52.0, "wgi_rule_of_law": 50.0,
           "fx_volatility": 8.0, "news_sentiment": -10.0, "discretion": 60.0},
}


def test_score_in_range_and_has_band():
    res = run_irmp("DO", DATASET)
    assert 0.0 <= res["irmp_score"] <= 100.0
    assert res["risk_band"] in {"Bajo", "Moderado", "Elevado", "Alto"}
    assert res["band_color"].startswith("#")


def test_weights_sum_to_one():
    assert round(sum(DIMENSION_WEIGHTS.values()), 6) == 1.0


def test_contributions_sum_to_overall():
    res = run_irmp("DO", DATASET)
    total = sum(d["contribution"] for d in res["dimensions"].values())
    assert abs(total - res["irmp_score"]) <= 0.5  # rounding tolerance


def test_unknown_country_raises():
    with pytest.raises(KeyError):
        run_irmp("XX", DATASET)


def test_all_dimensions_present():
    res = run_irmp("DO", DATASET)
    assert set(res["dimensions"].keys()) == set(DIMENSION_WEIGHTS.keys())
