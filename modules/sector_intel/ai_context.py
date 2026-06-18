"""Compact AI context for the sector attractiveness (IAI) narrative.

The narrative engine receives a SMALL, pre-digested context (IAI score, band,
the per-dimension contributions, the strongest/weakest dimension and the real-vs-
rubric provenance) — never the whole peer dataset — so prompts stay cheap and
focused (plan §5.2). Module-local, mirrors :mod:`macro_political_risk.ai_context`.
"""
from typing import Any, Dict, List, Optional

_DIM_LABELS = {
    "sector": "Sector (tamaño y crecimiento, BCRD)",
    "macro": "Exposición macro (contrato macro→sectorial)",
    "business": "Entorno de negocios",
    "talent": "Talento y mano de obra",
    "regulation": "Regulatoria",
}
# Dimensions sourced from real data today; the rest are declared rubric.
_LIVE_DIMS = {"sector", "macro"}


def sector_ai_context(
    latest: Dict[str, Any],
    sector_name: Optional[str] = None,
    sgps_detail: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compact context for one sector's IAI attractiveness assessment.

    *latest* is the ``/{sector}/latest`` payload (iai_score, iai_band, sgps_score,
    iai_breakdown). Surfaces dimensions sorted by contribution + strongest/weakest,
    flagging which are real vs declared rubric, so the narrative explains (not
    restates) the score and stays honest about provenance."""
    dims = latest.get("iai_breakdown") or {}
    rows: List[Dict[str, Any]] = []
    for key, d in dims.items():
        rows.append({
            "dimension": _DIM_LABELS.get(key, key),
            "score": d.get("score"),
            "weight": d.get("weight"),
            "contribution": d.get("contribution"),
            "provenance": "real" if key in _LIVE_DIMS else "rúbrica declarada",
        })
    scored = [r for r in rows if r["score"] is not None]
    strongest = max(scored, key=lambda r: r["score"], default=None)
    weakest = min(scored, key=lambda r: r["score"], default=None)
    rows.sort(key=lambda r: (r["contribution"] is None, -(r["contribution"] or 0)))

    return {
        "sector_code": latest.get("sector_code"),
        "sector_name": sector_name,
        "period": latest.get("period"),
        "iai_score": latest.get("iai_score"),
        "iai_band": latest.get("iai_band"),
        "sgps_score": latest.get("sgps_score"),
        "direction": "mayor score = mayor atractivo de inversión",
        "dimensions": rows,
        "strongest_dimension": strongest,
        "weakest_dimension": weakest,
        "acceleration": (sgps_detail or {}).get("acceleration_detail"),
        "note": "Real: sector (BCRD) y exposición macro. Rúbrica declarada: "
                "negocios, talento, regulatoria (suben a real con WGI/estudios ONE).",
    }
