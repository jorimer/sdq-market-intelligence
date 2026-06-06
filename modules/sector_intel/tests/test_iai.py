"""Tests for the IAI (delegates to shared/indices via sectoral doctrine)."""
from modules.sector_intel.scoring.iai import IAI_CONFIG, compute_iai

DATASET = {
    "turismo": {"gdp_growth": 5.0, "inflation_stability": 70, "ease_of_business": 65,
                "operating_cost": 40, "labor_availability": 75, "skills_index": 60,
                "regulatory_quality": 62, "regulatory_volatility": 30,
                "sector_growth": 8.0, "sector_size": 70},
    "energia": {"gdp_growth": 4.0, "inflation_stability": 68, "ease_of_business": 55,
                "operating_cost": 60, "labor_availability": 50, "skills_index": 65,
                "regulatory_quality": 58, "regulatory_volatility": 45,
                "sector_growth": 6.0, "sector_size": 60},
}


def test_iai_weights_sum_to_one():
    assert round(sum(IAI_CONFIG.dimension_weights.values()), 6) == 1.0


def test_iai_in_range_and_banded():
    res = compute_iai("turismo", DATASET)
    assert 0.0 <= res["iai_score"] <= 100.0
    assert res["band"] in {"Alto", "Medio", "Bajo"}
    assert set(res["dimensions"]) == set(IAI_CONFIG.dimension_weights)


def test_risk_increasing_inverted():
    # turismo has lower operating_cost than energia → inverted → better normalized
    res = compute_iai("turismo", DATASET)
    oc = res["dimensions"]["business"]["variables"]["operating_cost"]
    assert oc["inverted"] is True
    assert oc["normalized"] == 100.0  # lowest cost in peer set


def test_unknown_sector_raises():
    import pytest
    with pytest.raises(KeyError):
        compute_iai("inexistente", DATASET)
