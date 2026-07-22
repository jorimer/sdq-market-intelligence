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


# ─── Procedencia VIVA (no cableada) — lección Hallazgo 7 ──────────────


def _score_with_sources(sources):
    return {
        "esg_score": 55.0, "band": "Moderada", "period": "2025",
        "breakdown": {
            "dimensions": {
                "physical_risk": {"score": 60.0, "weight": 0.30, "contribution": 18.0},
                "transition_risk": {"score": 50.0, "weight": 0.25, "contribution": 12.5},
                "adaptive_capacity": {"score": 55.0, "weight": 0.25, "contribution": 13.75},
                "governance": {"score": 52.0, "weight": 0.20, "contribution": 10.4},
            },
            "sources": sources,
        },
    }


_ALL_LIVE = {
    "hurricane_exposure": "live", "climate_sensitivity": "live",
    "fossil_dependence": "live", "carbon_intensity": "live",
    "adaptation_readiness": "live", "economic_readiness": "live",
    "governance_quality": "live", "social_readiness": "live",
}


def test_provenance_is_read_from_the_run_not_hardcoded():
    """La misma función, con Ember caído, deja de decir que la transición es real."""
    live = climate_ai_context("DOM", _score_with_sources(_ALL_LIVE))
    fallen = dict(_ALL_LIVE, fossil_dependence="rubric", carbon_intensity="rubric")
    degraded = climate_ai_context("DOM", _score_with_sources(fallen))

    by_dim = {r["dimension"]: r["provenance"] for r in live["dimensions"]}
    assert all(p == "real" for p in by_dim.values())
    by_dim = {r["dimension"]: r["provenance"] for r in degraded["dimensions"]}
    assert by_dim["Riesgo de transición (fósil/carbono)"].startswith("supuesto de casa")


def test_note_never_claims_100_percent_when_a_dimension_fell_to_rubric():
    fallen = dict(_ALL_LIVE, fossil_dependence="rubric", carbon_intensity="rubric")
    ctx = climate_ai_context("DOM", _score_with_sources(fallen))
    assert "100%" not in ctx["note"]
    assert "procedencia" in ctx["note"]


def test_note_reports_all_real_when_the_run_is_all_real():
    ctx = climate_ai_context("DOM", _score_with_sources(_ALL_LIVE))
    assert "dato real" in ctx["note"]


def test_old_score_without_sources_map_does_not_assume_real():
    """Un score persistido antes de que existiera el mapa: sin registro ≠ real."""
    ctx = climate_ai_context("DOM", _score_with_sources({}))
    provs = {r["provenance"] for r in ctx["dimensions"]}
    assert provs == {"sin registro de procedencia"}
