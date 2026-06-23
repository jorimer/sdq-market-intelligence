"""Compact AI context for the IRMP risk-assessment narrative.

The narrative engine receives a SMALL, pre-digested context (score, band, the
per-dimension contributions and the strongest/weakest dimension) — never the
whole peer dataset — so prompts stay cheap and focused (plan §5.2). Module-local.
"""
from typing import Any, Dict, List

from modules.macro_political_risk.scoring.weights import DIMENSION_VARIABLES
from shared.narrative.derived import derived_figures

_DIM_LABELS = {
    "macro": "Macroeconómica",
    "external": "Externa",
    "political": "Político-institucional",
    "regulatory": "Regulatoria",
    "events": "Eventos",
}


def irmp_ai_context(result: Dict[str, Any], country_name: str | None = None) -> Dict[str, Any]:
    """Compact context for one country's IRMP risk assessment.

    *result* is :func:`run_irmp` output (score, band, per-dimension breakdown).
    Surfaces the dimensions sorted by contribution plus the strongest driver and
    weakest dimension, so the narrative can explain the score, not restate it.
    """
    dims = result.get("dimensions") or {}
    rows: List[Dict[str, Any]] = []
    for key, d in dims.items():
        rows.append({
            "dimension": _DIM_LABELS.get(key, key),
            "score": d.get("score"),
            "weight": d.get("weight"),
            "contribution": d.get("contribution"),
            "n_variables": len(d.get("variables") or {}),
            "n_expected": len(DIMENSION_VARIABLES.get(key, [])),
        })
    scored = [r for r in rows if r["score"] is not None]
    strongest = max(scored, key=lambda r: r["score"], default=None)
    weakest = min(scored, key=lambda r: r["score"], default=None)
    rows.sort(key=lambda r: (r["contribution"] is None, -(r["contribution"] or 0)))

    subcomp = [{"componente": r["dimension"], "score": r["score"], "peso": r["weight"]}
               for r in rows]
    return {
        "country_code": result.get("country_code"),
        "country_name": country_name,
        "irmp_score": result.get("irmp_score"),
        "risk_band": result.get("risk_band"),
        "peer_set_size": result.get("peer_set_size"),
        "direction": "mayor score = menor riesgo",
        "dimensions": rows,
        "strongest_dimension": strongest,
        "weakest_dimension": weakest,
        # ── canónico (cerebro) ── OJO: dirección invertida (mayor score = menor riesgo);
        # gap_al_techo grande = dimensión que MÁS aporta al riesgo.
        "score_global": result.get("irmp_score"),
        "sub_componentes": subcomp,
        "cifras_derivadas": derived_figures(score=result.get("irmp_score"),
                                            subcomponents=subcomp),
    }
