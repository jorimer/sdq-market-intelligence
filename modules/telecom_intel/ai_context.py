"""Compact AI context for the telecom-development (IDT) narrative.

Small, pre-digested context (IDT score, band, the three real penetration/quality
dimensions and revenue growth as context) — honest about the bulletin's age.
Module-local, mirrors :mod:`energy_intel.ai_context`.
"""
from typing import Any, Dict, List

_DIM_LABELS = {
    "mobile_penetration": "Penetración móvil/telefónica (líneas por 100 hab.)",
    "internet_penetration": "Penetración de internet (suscripciones por 100 hab.)",
    "broadband_quality": "Calidad: banda ancha (% del internet)",
}


def telecom_ai_context(index: Dict[str, Any], period: str) -> Dict[str, Any]:
    """Compact context for the national telecom-development assessment.

    *index* is ``compute_telecom_index`` output. Surfaces the real dimensions and the
    headline penetration figures so the narrative explains the score and stays honest."""
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
    m = index.get("metrics") or {}
    return {
        "period": period,
        "idt_score": index.get("telecom_score"),
        "band": index.get("band"),
        "coverage": index.get("coverage"),
        "direction": "mayor score = más desarrollo/conectividad telecom",
        "dimensions": rows,
        "mobile_penetration": m.get("mobile_penetration"),
        "internet_penetration": m.get("internet_penetration"),
        "broadband_share": m.get("broadband_share"),
        "revenue_growth": m.get("revenue_growth"),
        "score_global": index.get("telecom_score"),
        "source": "INDOTEL (boletín trimestral de indicadores), datos abiertos",
        "note": "Sobre dato real INDOTEL: líneas, suscripciones a internet y banda ancha; "
                "penetración sobre población censal ONE. El boletín público más reciente es "
                "anterior al período actual (la frescura lo refleja). No inventes cifras.",
    }
