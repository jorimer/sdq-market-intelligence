"""Compact AI context for the trade-resilience (Comercio) narrative.

The narrative engine receives a SMALL, pre-digested context (resilience score,
concentration, import dependency and the top export chapters) — never the full
flow set — so prompts stay cheap and focused (plan §5.2). Module-local, mirrors
:mod:`macro_political_risk.ai_context`. Source: DGA (Aduanas), by HS chapter.
"""
from typing import Any, Dict, List


def trade_ai_context(score: Dict[str, Any]) -> Dict[str, Any]:
    """Compact context for the national trade-resilience assessment.

    *score* is the ``/trade-intel/score`` payload (resilience, HHI, diversification,
    import dependency, totals, top export chapters). Surfaces the top export
    chapters with shares so the narrative explains concentration and dependence,
    not just restates the score."""
    top: List[Dict[str, Any]] = score.get("top_export_products") or []
    return {
        "period": score.get("period"),
        "resilience_score": score.get("resilience_score"),
        "export_diversification": score.get("export_diversification"),
        "hhi_exports": score.get("hhi_exports"),
        "import_dependency": score.get("import_dependency"),
        "total_exports": score.get("total_exports"),
        "total_imports": score.get("total_imports"),
        "n_chapters_export": score.get("n_products_export"),
        "top_export_chapters": [
            {"chapter": p.get("product"), "share": p.get("share")} for p in top[:5]
        ],
        "direction": "mayor resiliencia = más diversificado y menos dependiente",
        "source": "DGA (Aduanas), por capítulo arancelario (HS)",
        "unit": "USD millones",
        "note": "Diversificación > volumen; medir dependencia, no solo apertura. "
                "Sin detalle por país socio (no disponible de forma automatizable).",
    }
