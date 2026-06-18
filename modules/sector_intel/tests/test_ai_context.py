"""Tests for the sector IAI AI-context builder (Gate D). Pure, offline."""
from modules.sector_intel.ai_context import sector_ai_context

_LATEST = {
    "sector_code": "turismo",
    "period": "2024",
    "iai_score": 61.2,
    "iai_band": "Atractivo",
    "sgps_score": 58.0,
    "iai_breakdown": {
        "sector": {"score": 80.0, "weight": 0.3, "contribution": 24.0},
        "macro": {"score": 55.0, "weight": 0.2, "contribution": 11.0},
        "business": {"score": 50.0, "weight": 0.2, "contribution": 10.0},
        "talent": {"score": 50.0, "weight": 0.15, "contribution": 7.5},
        "regulation": {"score": 40.0, "weight": 0.15, "contribution": 6.0},
    },
}


def test_context_is_compact_and_explains_drivers():
    ctx = sector_ai_context(_LATEST, sector_name="Turismo")
    assert ctx["sector_code"] == "turismo" and ctx["sector_name"] == "Turismo"
    assert ctx["iai_score"] == 61.2 and ctx["iai_band"] == "Atractivo"
    # Dimensions sorted by contribution desc (sector first).
    assert ctx["dimensions"][0]["dimension"].startswith("Sector")
    # Strongest = sector (80), weakest = regulation (40).
    assert ctx["strongest_dimension"]["score"] == 80.0
    assert ctx["weakest_dimension"]["score"] == 40.0


def test_provenance_flags_real_vs_rubric():
    ctx = sector_ai_context(_LATEST)
    prov = {r["dimension"].split(" ")[0]: r["provenance"] for r in ctx["dimensions"]}
    assert prov["Sector"] == "real" and prov["Exposición"] == "real"
    assert prov["Entorno"] == "rúbrica declarada"          # business
    assert prov["Talento"] == "rúbrica declarada"


def test_handles_missing_breakdown():
    ctx = sector_ai_context({"sector_code": "x", "iai_score": None, "iai_breakdown": None})
    assert ctx["dimensions"] == []
    assert ctx["strongest_dimension"] is None and ctx["weakest_dimension"] is None
