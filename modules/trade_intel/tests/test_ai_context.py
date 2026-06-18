"""Tests for the trade-resilience AI-context builder (Gate D). Pure, offline."""
from modules.trade_intel.ai_context import trade_ai_context

_SCORE = {
    "period": "2026-Q1",
    "resilience_score": 67.3,
    "export_diversification": 89.8,
    "hhi_exports": 0.1017,
    "import_dependency": 0.6652,
    "total_exports": 3736.87,
    "total_imports": 7423.69,
    "n_products_export": 97,
    "top_export_products": [
        {"product": "Perlas finas y piedras preciosas", "share": 0.236},
        {"product": "Instrumentos de óptica/médicos", "share": 0.138},
        {"product": "Tabaco", "share": 0.097},
        {"product": "Maquinaria eléctrica", "share": 0.094},
        {"product": "Plástico", "share": 0.048},
        {"product": "Sexto producto (no debe aparecer)", "share": 0.02},
    ],
}


def test_context_is_compact_and_surfaces_top_chapters():
    ctx = trade_ai_context(_SCORE)
    assert ctx["period"] == "2026-Q1"
    assert ctx["resilience_score"] == 67.3 and ctx["import_dependency"] == 0.6652
    # Only the top 5 chapters travel in the prompt.
    assert len(ctx["top_export_chapters"]) == 5
    assert ctx["top_export_chapters"][0] == {"chapter": "Perlas finas y piedras preciosas", "share": 0.236}
    assert "país socio" in ctx["note"]  # honest about the gap


def test_handles_missing_score():
    ctx = trade_ai_context({})
    assert ctx["resilience_score"] is None
    assert ctx["top_export_chapters"] == []
