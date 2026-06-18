"""Compact AI context for the climate-resilience (IRC) narrative.

The narrative engine receives a SMALL, pre-digested context (IRC score, band, the
per-dimension contributions, the strongest/weakest dimension and the country's
position in the panel) — never the whole peer dataset — so prompts stay cheap and
focused. National (per country), mirrors :mod:`macro_political_risk.ai_context`.
"""
from typing import Any, Dict, List, Optional

_DIM_LABELS = {
    "physical_risk": "Riesgo físico (huracán/clima)",
    "transition_risk": "Riesgo de transición (fósil/carbono)",
    "adaptive_capacity": "Capacidad adaptativa",
    "governance": "Gobernanza",
}
# Real source feeding each dimension (the IRC is 100% real data).
_DIM_SOURCE = {
    "physical_risk": "HURDAT2 (NOAA) + ND-GAIN",
    "transition_risk": "Ember (electricidad)",
    "adaptive_capacity": "ND-GAIN",
    "governance": "ND-GAIN",
}


def climate_ai_context(
    entity_key: str,
    score: Dict[str, Any],
    country_name: Optional[str] = None,
    rank: Optional[int] = None,
    n_countries: Optional[int] = None,
    distribution: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compact context for one country's IRC climate-resilience assessment.

    *score* carries ``esg_score``, ``band`` and ``breakdown.dimensions``. Surfaces
    dimensions sorted by contribution + strongest/weakest, the real source per
    dimension, and the country's rank in the panel — so the narrative explains the
    score (distribution > average) and stays honest about provenance."""
    dims = (score.get("breakdown") or {}).get("dimensions") or {}
    rows: List[Dict[str, Any]] = []
    for key, d in dims.items():
        rows.append({
            "dimension": _DIM_LABELS.get(key, key),
            "score": d.get("score"),
            "weight": d.get("weight"),
            "contribution": d.get("contribution"),
            "source": _DIM_SOURCE.get(key, "real"),
        })
    scored = [r for r in rows if r["score"] is not None]
    strongest = max(scored, key=lambda r: r["score"], default=None)
    weakest = min(scored, key=lambda r: r["score"], default=None)
    rows.sort(key=lambda r: (r["contribution"] is None, -(r["contribution"] or 0)))

    return {
        "entity_key": entity_key,
        "country_name": country_name,
        "period": score.get("period"),
        "irc_score": score.get("esg_score"),
        "band": score.get("band"),
        "direction": "mayor score = mayor resiliencia / menor riesgo climático",
        "rank": rank,
        "n_countries": n_countries,
        "distribution": distribution,         # mean/spread across the panel
        "dimensions": rows,
        "strongest_dimension": strongest,
        "weakest_dimension": weakest,
        "note": "IRC 100% dato real: físico = huracanes HURDAT2/NOAA; transición = "
                "matriz eléctrica de Ember (fósil/carbono); adaptativa y gobernanza = "
                "ND-GAIN. Panel Caribe/LatAm como conjunto de pares.",
    }
