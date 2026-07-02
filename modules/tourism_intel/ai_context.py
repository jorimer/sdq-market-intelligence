"""Compact AI context for the tourism-traction (ITT) narrative.

The narrative engine receives a SMALL, pre-digested context (ITT score, band, the
dimensions with their CAGR/contribution, and the latest-year levels) — never raw
series — so prompts stay cheap and honest about provenance. Module-local, mirrors
:mod:`free_zones_intel.ai_context`.
"""
from typing import Any, Dict, List

_DIM_LABELS = {
    "total_demand": "Demanda total (CAGR llegadas de no residentes, ONE)",
    "foreign_demand": "Demanda extranjera (CAGR extranjeros no residentes, ONE)",
    "recovery": "Resiliencia / recuperación (nivel vs pico pre-pandemia, ONE)",
    "diversification": "Diversificación de mercados (HHI por región emisora, ONE)",
}
# cada dimensión guarda sus métricas bajo una clave canónica
_METRIC_KEY = {"total_demand": "total_demand", "foreign_demand": "foreign_demand",
               "recovery": "recovery", "diversification": "diversification"}


def tourism_ai_context(index: Dict[str, Any], period: str) -> Dict[str, Any]:
    """Compact context for the tourism-sector traction assessment.

    *index* is the ``compute_tourism_index`` output. Surfaces the dimensions (score +
    metric + contribution) and the latest-year levels so the narrative explains the
    score and stays honest about provenance/coverage."""
    dims = index.get("dimensions") or {}
    rows: List[Dict[str, Any]] = []
    for key, d in dims.items():
        m = index.get(_METRIC_KEY.get(key, "")) or {}
        rows.append({
            "dimension": _DIM_LABELS.get(key, key),
            "score": d.get("score"),
            "weight": d.get("weight"),
            "contribution": d.get("contribution"),
            "cagr_pct": m.get("cagr"),       # demanda total/extranjera
            "recovery_pct": m.get("ratio"),  # recuperación
            "hhi": m.get("hhi"),             # diversificación
            "provenance": d.get("provenance"),
        })
    levels = index.get("levels") or {}
    recovery = index.get("recovery") or {}
    diversification = index.get("diversification") or {}
    return {
        "period": period,
        "itt_score": index.get("itt_score"),
        "band": index.get("band"),
        "coverage": index.get("coverage"),
        "direction": "mayor score = destino turístico con más tracción de demanda y resiliencia",
        "dimensions": rows,
        "nonresident_arrivals": levels.get("nonresident"),
        "foreign_arrivals": levels.get("foreign"),
        "top_origin_region": diversification.get("top_region"),
        "top_origin_share_pct": diversification.get("top_share"),
        "recovery_vs_prepandemic_pct": recovery.get("ratio"),
        "prepandemic_peak_year": recovery.get("peak_year"),
        "score_global": index.get("itt_score"),
        "source": "ONE (Oficina Nacional de Estadística), llegadas vía aérea, datos abiertos",
        "note": ("Sobre dato real ONE: llegadas anuales de no residentes vía aérea por "
                 "mercado de origen. Índice de tracción de DEMANDA (volumen, recuperación, "
                 "diversificación de mercados). NO cubre oferta hotelera, ocupación, ni "
                 "ingresos por turismo (divisas) — el BCRD discontinuó esas series "
                 "estructuradas en 2018-2019 y hoy solo viven en PDFs narrativos, sin serie "
                 "limpia; no los inventes. Sin validación retrospectiva de resultados."),
    }
