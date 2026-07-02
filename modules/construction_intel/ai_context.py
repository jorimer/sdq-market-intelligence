"""Compact AI context for the construction conjuncture (ICC) narrative.

The narrative engine receives a SMALL, pre-digested context (ICC score, band, the four
dimensions with their metric + contribution, and the latest-year levels) — never raw
series — so prompts stay cheap and honest about provenance. Module-local, mirrors
:mod:`free_zones_intel.ai_context`.
"""
from typing import Any, Dict, List

_DIM_LABELS = {
    "production": "Producción del sector (crec. real PIB construcción 3y, BCRD)",
    "pipeline": "Pipeline de permisos (CAGR m² licenciados 3y, MIVHED)",
    "typology_diversification": "Diversificación tipológica (HHI por tipología, MIVHED)",
    "geographic_breadth": "Amplitud geográfica (HHI por provincia, MIVHED)",
}
# clave de dimensión → bloque de métricas + campo de "ritmo" a exponer
_METRIC = {"production": ("production", "avg_growth"), "pipeline": ("pipeline", "cagr"),
           "typology_diversification": ("typology", "hhi"),
           "geographic_breadth": ("geography", "hhi")}


def construction_ai_context(index: Dict[str, Any], period: str) -> Dict[str, Any]:
    """Compact context for the construction conjuncture assessment.

    *index* is the ``compute_construction_index`` output. Surfaces the dimensions (score +
    metric + contribution) and the latest-year levels so the narrative explains the score
    and stays honest about provenance/coverage."""
    dims = index.get("dimensions") or {}
    rows: List[Dict[str, Any]] = []
    for key, d in dims.items():
        block_key, metric_key = _METRIC.get(key, ("", ""))
        m = index.get(block_key) or {}
        rows.append({
            "dimension": _DIM_LABELS.get(key, key),
            "score": d.get("score"),
            "weight": d.get("weight"),
            "contribution": d.get("contribution"),
            "metric": m.get(metric_key),
            "provenance": d.get("provenance"),
        })
    levels = index.get("levels") or {}
    inv = levels.get("investment_dop")
    return {
        "period": period,
        "icc_score": index.get("icc_score"),
        "band": index.get("band"),
        "coverage": index.get("coverage"),
        "direction": "mayor score = construcción con mejor coyuntura (producción + pipeline)",
        "dimensions": rows,
        "permits": levels.get("permits"),
        "sqm_licensed": levels.get("sqm"),
        "investment_licensed_mm_dop": round(inv / 1e6) if inv is not None else None,
        "construction_gdp_growth_latest_pct": levels.get("prod_growth_latest"),
        "construction_gdp_growth_3y_pct": levels.get("prod_growth_3y"),
        "top_typology": levels.get("top_typology"),
        "top_typology_share_pct": levels.get("top_typology_share"),
        "top_province": levels.get("top_province"),
        "top_province_share_pct": levels.get("top_province_share"),
        "score_global": index.get("icc_score"),
        "source": "MIVHED (licencias de construcción) + BCRD (PIB construcción), datos abiertos",
        "note": ("Sobre dato real: PIPELINE de permisos (MIVHED, líder) + PRODUCCIÓN "
                 "efectiva (PIB construcción BCRD). Índice de coyuntura — distingue "
                 "actividad LÍDER (permisos) de PRODUCCIÓN realizada (PIB). Agregado "
                 "nacional anual; los permisos MIVHED arrancan en 2022 (historia corta para "
                 "el flujo de permisos); sin validación retrospectiva de resultados. La inversión licenciada es nominal "
                 "(RD$); no la confundas con la inversión ejecutada."),
    }
