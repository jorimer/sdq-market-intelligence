"""Compact AI context for the multidimensional development (IDM) narrative.

The narrative engine receives a SMALL, pre-digested context (IDM score, band,
the per-dimension contributions, the strongest/weakest dimension, the real-vs-
rubric provenance and the region's position in the distribution) — never the
whole peer dataset — so prompts stay cheap and focused (plan §5.2). Module-local,
mirrors :mod:`macro_political_risk.ai_context`.
"""
from typing import Any, Dict, List, Optional

_DIM_LABELS = {
    "health": "Salud",
    "education": "Educación",
    "living_standards": "Nivel de vida",
    "inclusion": "Inclusión",
}
# Which variables feed each IDM dimension (mirrors shared/doctrine/social.yaml).
_DIM_VARS = {
    "health": ["life_expectancy", "child_mortality"],
    "education": ["literacy_rate", "schooling_years", "secondary_coverage"],
    "living_standards": ["income_per_capita", "poverty_rate"],
    "inclusion": ["financial_inclusion", "informality_rate"],
}


def _provenance(dim_key: str, sources: Optional[Dict[str, str]]) -> str:
    """real / parcial / rúbrica declarada, from the live-vs-rubric source map."""
    if not sources:
        return "desconocida"
    live = sum(1 for v in _DIM_VARS.get(dim_key, []) if sources.get(v) == "live")
    total = len(_DIM_VARS.get(dim_key, []))
    if live == 0:
        return "rúbrica declarada"
    return "real" if live == total else "parcial (real + rúbrica)"


def social_ai_context(
    entity_key: str,
    score: Dict[str, Any],
    region_name: Optional[str] = None,
    sources: Optional[Dict[str, str]] = None,
    rank: Optional[int] = None,
    n_regions: Optional[int] = None,
    distribution: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compact context for one region's IDM development assessment.

    *score* carries ``development_score``, ``band`` and ``breakdown`` (the dimension
    dict). Surfaces dimensions sorted by contribution + strongest/weakest, flags
    each dimension's provenance (real/partial/rubric), and locates the region in
    the distribution so the narrative reads inequality, not just the mean."""
    dims = score.get("breakdown") or {}
    rows: List[Dict[str, Any]] = []
    for key, d in dims.items():
        rows.append({
            "dimension": _DIM_LABELS.get(key, key),
            "score": d.get("score"),
            "weight": d.get("weight"),
            "contribution": d.get("contribution"),
            "provenance": _provenance(key, sources),
        })
    scored = [r for r in rows if r["score"] is not None]
    strongest = max(scored, key=lambda r: r["score"], default=None)
    weakest = min(scored, key=lambda r: r["score"], default=None)
    rows.sort(key=lambda r: (r["contribution"] is None, -(r["contribution"] or 0)))

    return {
        "entity_key": entity_key,
        "region_name": region_name,
        "period": score.get("period"),
        "development_score": score.get("development_score"),
        "band": score.get("band"),
        "direction": "mayor score = mayor desarrollo/bienestar",
        "rank": rank,
        "n_regions": n_regions,
        "distribution": distribution,  # mean/spread/cv across regions (inequality)
        "dimensions": rows,
        "strongest_dimension": strongest,
        "weakest_dimension": weakest,
        "note": "Dato real: pobreza, alfabetización y cobertura secundaria (ONE por "
                "región); salud (WDI nacional); ingreso, informalidad y escolaridad (ONE "
                "nacional); inclusión financiera (BM Findex). Las 9 variables del IDM en "
                "dato real; la diferenciación regional la dan pobreza, alfabetización y "
                "cobertura (las nacionales se aplican planas a todas las regiones).",
    }
