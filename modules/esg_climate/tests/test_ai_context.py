"""Tests for the IRC climate AI-context builder (Gate D). Pure, offline."""
from modules.esg_climate.ai_context import climate_ai_context

_SCORE = {
    "period": "2023",
    "esg_score": 35.65,
    "band": "Baja",
    "breakdown": {
        "dimensions": {
            "physical_risk": {"score": 22.54, "weight": 0.30, "contribution": 6.76},
            "transition_risk": {"score": 22.83, "weight": 0.25, "contribution": 5.71},
            "adaptive_capacity": {"score": 45.55, "weight": 0.25, "contribution": 11.39},
            "governance": {"score": 58.98, "weight": 0.20, "contribution": 11.80},
        },
    },
}


def test_context_surfaces_drivers_rank_and_sources():
    ctx = climate_ai_context(
        "DOM", _SCORE, country_name="República Dominicana",
        rank=22, n_countries=24, distribution={"mean": 55.0, "spread": 60.0},
    )
    assert ctx["entity_key"] == "DOM" and ctx["country_name"] == "República Dominicana"
    assert ctx["irc_score"] == 35.65 and ctx["band"] == "Baja"
    assert ctx["rank"] == 22 and ctx["n_countries"] == 24
    # Sorted by contribution desc → governance first.
    assert ctx["dimensions"][0]["dimension"].startswith("Gobernanza")
    # Strongest = governance (59); weakest = physical (22.54).
    assert ctx["strongest_dimension"]["score"] == 58.98
    assert ctx["weakest_dimension"]["score"] == 22.54


def test_context_names_the_real_source_per_dimension():
    ctx = climate_ai_context("DOM", _SCORE)
    by_dim = {r["dimension"]: r["source"] for r in ctx["dimensions"]}
    assert "HURDAT2" in by_dim["Riesgo físico (huracán/clima)"]
    assert "Ember" in by_dim["Riesgo de transición (fósil/carbono)"]


def test_handles_missing_breakdown():
    ctx = climate_ai_context("DOM", {"esg_score": None})
    assert ctx["dimensions"] == []
    assert ctx["strongest_dimension"] is None
