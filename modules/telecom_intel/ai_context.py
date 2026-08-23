"""Compact AI context for the telecom-development (IDT) narrative.

Small, pre-digested context (IDT score, band, the three real penetration/quality
dimensions and revenue growth as context) — honest about the bulletin's age.
Module-local, mirrors :mod:`energy_intel.ai_context`.

**El emisor se COMPUTA del período.** Este contexto decía «source: INDOTEL (boletín
trimestral de indicadores)» en una constante, y lo decía para TODOS los períodos — incluidos
los anuales, que produce la UIT desde que INDOTEL se congeló en 2022-Q1 y sus trimestres se
retiraron de la base. El endpoint tenía el mismo defecto, se arregló y quedó su regresión
(``tests/test_source_label.py``); el contexto de IA no, así que el narrador siguió
atribuyendo al emisor equivocado. Es la doctrina de siempre: son superficies distintas y
arreglar una sola deja el documento contradiciéndose.

**Y la atribución no es cortesía.** La UIT autorizó por escrito (2026-08-18) el uso comercial
de los datos del DataHub **a condición de citarla**. El texto no se escribe acá: sale de
``shared.data.licenses``, que es donde vive la obligación, vía
:func:`modules.telecom_intel.sources.emisor_del_periodo`.
"""
from typing import Any, Dict, List

from modules.telecom_intel.sources import emisor_del_periodo
from shared.narrative.atribucion import bloque_de_atribucion

_DIM_LABELS = {
    "mobile_penetration": "Penetración móvil/telefónica (líneas por 100 hab.)",
    "internet_penetration": "Penetración de internet (suscripciones por 100 hab.)",
    "broadband_quality": "Calidad: banda ancha (% del internet)",
}


def telecom_ai_context(index: Dict[str, Any], period: str) -> Dict[str, Any]:
    """Compact context for the national telecom-development assessment.

    *index* is ``compute_telecom_index`` output. Surfaces the real dimensions and the
    headline penetration figures so the narrative explains the score and stays honest."""
    emisor = emisor_del_periodo(period)
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
        "note": ("Sobre dato real de " + emisor.label + ": penetración móvil, banda ancha "
                 "móvil y fija, y hogares con internet. No inventes cifras."),
        # `source` + la atribución que la LICENCIA exige, computadas del emisor. Acá el
        # emisor sale del PERÍODO —con "Q" es INDOTEL, sin "Q" la UIT— porque este eje
        # tiene dos en la misma serie; en los demás es fijo pero igual sale del conector.
        **bloque_de_atribucion(emisor),
    }
