"""Compact AI context for the electric-sector resilience (IRSE) narrative.

The narrative engine receives a SMALL, pre-digested context (IRSE score, band, the
two real dimensions with their contributions, and the declared transition gap) —
never raw series — so prompts stay cheap and honest about provenance. Module-local,
mirrors :mod:`trade_intel.ai_context`.
"""
from typing import Any, Dict, List

_DIM_LABELS = {
    "capacity_adequacy": "Adecuación de capacidad (parque instalado, SIE)",
    "service_quality": "Calidad de servicio (reclamaciones, SIE)",
    "energy_transition": "Transición energética (renovable/carbono)",
}


def energy_ai_context(index: Dict[str, Any], period: str) -> Dict[str, Any]:
    """Compact context for the national electric-sector resilience assessment.

    *index* is the ``compute_energy_index`` output (energy_score, band, coverage,
    dimensions, capacity, service). Surfaces the real dimensions and flags the
    transition gap so the narrative explains the score and stays honest."""
    dims = index.get("dimensions") or {}
    rows: List[Dict[str, Any]] = []
    for key, d in dims.items():
        rows.append({
            "dimension": _DIM_LABELS.get(key, key),
            "score": d.get("score"),
            "weight": d.get("weight"),
            "contribution": d.get("contribution"),
            "provenance": d.get("provenance"),
        })
    cap = index.get("capacity") or {}
    svc = index.get("service") or {}
    return {
        "period": period,
        "irse_score": index.get("energy_score"),
        "band": index.get("band"),
        "coverage": index.get("coverage"),
        "direction": "mayor score = mayor resiliencia del sector eléctrico",
        "dimensions": rows,
        "capacity_mw": cap.get("capacity_mw"),
        "capacity_growth_cagr_3y": cap.get("cagr_3y"),
        "service_backlog_months": svc.get("backlog_months"),
        # canónico (cerebro): el score global; sin sub-componentes ponderados completos
        # (1 dimensión es brecha) → el detector determinista no aplica, el guard es el LLM.
        "score_global": index.get("energy_score"),
        "source": "SIE (Superintendencia de Electricidad), datos abiertos",
        "note": "Sobre dato real SIE: capacidad instalada + reclamaciones. La TRANSICIÓN "
                "(penetración renovable / intensidad de carbono) es BRECHA declarada — el "
                "dato confiable (generación por tecnología) está en OC-SENI (pendiente). "
                "No se afirma transición sin dato.",
    }
