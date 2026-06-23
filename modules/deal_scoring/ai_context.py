"""Compact AI context for the Deal Scoring narrative (cerebro route).

The deal score is a weighted composite of drivers (rúbrica anclada a IRMP/IAI/IRC),
so it maps to the canonical cerebro shape: score_global + sub_componentes (drivers
with weights) + cifras_derivadas. Module-local.
"""
from typing import Any, Dict, List, Optional

from shared.narrative.derived import derived_figures

_FACTOR_LABELS = {
    "promoter_track_record": "Track record del promotor",
    "financial_quality": "Calidad financiera",
    "market_validation": "Validación de mercado (IAI)",
    "regulatory_readiness": "Preparación regulatoria (IRMP)",
    "climate": "Clima (IRC)",
    "deal_momentum": "Momentum del deal",
}


def deal_ai_context(
    body: Dict[str, Any],
    result: Dict[str, Any],
    anchor_sources: Dict[str, Any],
    country: Optional[str] = None,
    sector: Optional[str] = None,
) -> Dict[str, Any]:
    """Compact context for one deal's score narrative. *result* is compute_deal_score
    output (score, confidence, key_factors[{factor,value,weight,contribution,source}])."""
    factors: List[Dict[str, Any]] = result.get("key_factors") or []
    subcomp = [
        {"componente": _FACTOR_LABELS.get(f["factor"], f["factor"]),
         "score": f.get("value"), "peso": f.get("weight"), "fuente": f.get("source")}
        for f in factors
    ]
    return {
        "deal": {
            "nombre": body.get("deal_name"), "tipo": body.get("deal_type"),
            "sector": sector, "pais": country, "etapa": body.get("deal_stage"),
            "tamano_usd": body.get("deal_size_usd"),
            "equity_pct": body.get("equity_required_pct"),
        },
        "score": result.get("score"),
        "confianza": result.get("confidence"),
        "direction": "mayor score = deal más atractivo / mayor probabilidad de cierre",
        "drivers": factors,
        "contexto_ejes": anchor_sources,
        "metodo": result.get("method"),
        "note": "Índice de atractivo/cierre, NO una probabilidad. Rúbrica declarada "
                "(cold-start) anclada a IRMP/IAI/IRC; varios drivers son juicio del analista.",
        # ── canónico (cerebro) ──
        "score_global": result.get("score"),
        "sub_componentes": subcomp,
        "cifras_derivadas": derived_figures(
            score=result.get("score"),
            subcomponents=[{"componente": s["componente"], "score": s["score"],
                            "peso": s["peso"]} for s in subcomp],
        ),
    }
