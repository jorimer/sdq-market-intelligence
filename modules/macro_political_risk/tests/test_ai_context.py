"""Tests for the IRMP AI context builder."""
from modules.macro_political_risk.ai_context import irmp_ai_context


def _result():
    return {
        "country_code": "DO",
        "irmp_score": 50.2,
        "risk_band": "Elevado",
        "peer_set_size": 5,
        "dimensions": {
            "macro": {"score": 42.0, "weight": 0.30, "contribution": 12.6,
                      "variables": {"a": {}, "b": {}}},
            "political": {"score": 70.0, "weight": 0.25, "contribution": 17.5,
                          "variables": {"x": {}}},
            "events": {"score": None, "weight": 0.10, "contribution": None, "variables": {}},
        },
    }


def test_context_is_compact_and_sorted_by_contribution():
    ctx = irmp_ai_context(_result(), country_name="República Dominicana")
    assert ctx["country_code"] == "DO"
    assert ctx["irmp_score"] == 50.2
    assert ctx["risk_band"] == "Elevado"
    assert ctx["country_name"] == "República Dominicana"
    # dimensions sorted by contribution desc; the None-contribution one goes last
    dims = ctx["dimensions"]
    assert dims[0]["dimension"] == "Político-institucional"   # 17.5
    assert dims[1]["dimension"] == "Macroeconómica"           # 12.6
    assert dims[-1]["dimension"] == "Eventos"                 # None → last
    # labels translated, coverage carried
    assert dims[0]["n_variables"] == 1


def test_strongest_and_weakest_ignore_missing_scores():
    ctx = irmp_ai_context(_result())
    assert ctx["strongest_dimension"]["dimension"] == "Político-institucional"  # 70
    assert ctx["weakest_dimension"]["dimension"] == "Macroeconómica"            # 42
    # the None-score 'events' dimension is excluded from strongest/weakest
    assert ctx["weakest_dimension"]["score"] == 42.0
