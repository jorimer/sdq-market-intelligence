"""Tests for the IDM development AI-context builder (Gate D). Pure, offline."""
from modules.social_dev.ai_context import social_ai_context

_SCORE = {
    "period": "2024",
    "development_score": 52.8,
    "band": "Medio",
    "breakdown": {
        "health": {"score": 60.0, "weight": 0.25, "contribution": 15.0},
        "education": {"score": 67.0, "weight": 0.25, "contribution": 16.75},
        "living_standards": {"score": 45.0, "weight": 0.25, "contribution": 11.25},
        "inclusion": {"score": 50.0, "weight": 0.25, "contribution": 12.5},
    },
}
# Education partially live (literacy real, schooling rubric); living_standards
# partial (poverty live, income rubric); health all live; inclusion all rubric.
_SOURCES = {
    "life_expectancy": "live", "child_mortality": "live",
    "literacy_rate": "live", "schooling_years": "rubric",
    "income_per_capita": "rubric", "poverty_rate": "live",
    "financial_inclusion": "rubric", "informality_rate": "rubric",
}


def test_context_surfaces_drivers_rank_and_distribution():
    ctx = social_ai_context(
        "enriquillo", _SCORE, region_name="Enriquillo", sources=_SOURCES,
        rank=9, n_regions=10, distribution={"mean": 52.0, "spread": 16.6, "cv": 0.1},
    )
    assert ctx["entity_key"] == "enriquillo" and ctx["region_name"] == "Enriquillo"
    assert ctx["rank"] == 9 and ctx["n_regions"] == 10
    assert ctx["distribution"]["spread"] == 16.6
    # Sorted by contribution desc → education first.
    assert ctx["dimensions"][0]["dimension"] == "Educación"
    assert ctx["strongest_dimension"]["score"] == 67.0
    assert ctx["weakest_dimension"]["score"] == 45.0


def test_provenance_per_dimension():
    ctx = social_ai_context("x", _SCORE, sources=_SOURCES)
    prov = {r["dimension"]: r["provenance"] for r in ctx["dimensions"]}
    assert prov["Salud"] == "real"                              # both live
    assert prov["Educación"] == "parcial (real + rúbrica)"      # literacy live, schooling rubric
    assert prov["Nivel de vida"] == "parcial (real + rúbrica)"  # poverty live, income rubric
    assert prov["Inclusión"] == "rúbrica declarada"             # both rubric


def test_provenance_unknown_without_sources():
    ctx = social_ai_context("x", _SCORE)
    assert all(r["provenance"] == "desconocida" for r in ctx["dimensions"])
