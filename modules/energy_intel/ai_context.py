"""Compact AI context for the electric-sector resilience (IRSE) narrative.

The narrative engine receives a SMALL, pre-digested context (IRSE score, band, the
two real dimensions with their contributions, and the declared transition gap) —
never raw series — so prompts stay cheap and honest about provenance. Module-local,
mirrors :mod:`trade_intel.ai_context`.
"""
from typing import Any, Dict, List, Optional
from shared.data.generation_client import GenerationMixClient
from shared.data.sie_client import SIEClient
from shared.narrative.atribucion import Fuente, bloque_de_atribucion


#: Los DOS emisores del eje, construidos de su conector (etiqueta + licencia juntas).
_SIE = Fuente.de_cliente(
    SIEClient, descripcion="SIE (capacidad instalada y reclamaciones), datos abiertos")
_ONE_GEN = Fuente.de_cliente(
    GenerationMixClient, descripcion="ONE (generación por tecnología), datos abiertos")


_DIM_LABELS = {
    "capacity_adequacy": "Adecuación de capacidad (parque instalado, SIE)",
    "service_quality": "Calidad de servicio (reclamaciones, SIE)",
    "energy_transition": "Transición energética (penetración renovable, ONE)",
}


def _financiamiento(perfil: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """El crédito y el costo laboral del sector, para el contexto del modelo.

    Delega en `shared.perfil_del_sector.contexto_de_financiamiento`, que es el ÚNICO cuerpo:
    lo comparten los cuatro ejes cableados. Cuatro copias de la misma forma es como una se
    queda atrás, y este repo lo pagó con un serializador copiado a mano.
    """
    from shared.perfil_del_sector import contexto_de_financiamiento
    return contexto_de_financiamiento(perfil, "energia")


def energy_ai_context(index: Dict[str, Any], period: str,
                      perfil: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
    tra = index.get("transition") or {}
    transition_measured = tra.get("score") is not None
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
        # Participación en la MATRIZ DE GENERACIÓN (ONE), no en capacidad instalada. El
        # nombre lo dice porque justo arriba viaja `capacity_mw`: sin el sujeto, la lectura
        # natural es «% de la capacidad», que es otra cifra y otra conclusión.
        "renewable_share_of_generation_pct": tra.get("renewable_share"),
        "renewable_delta_5y_pp": tra.get("delta_5y"),
        "renewable_year": tra.get("year"),
        # canónico (cerebro): el score global; el detector determinista no aplica
        # (cuando alguna dimensión es brecha) → el guard es el LLM.
        "score_global": index.get("energy_score"),
        **_financiamiento(perfil),
        **bloque_de_atribucion(_SIE, _ONE_GEN),
        "note": (
            "Sobre dato real: capacidad instalada + reclamaciones (SIE) y penetración "
            "renovable de la matriz (ONE, eólica+hidráulica+solar vs meta Ley 57-07 25 %). "
            "Las 3 dimensiones del IRSE con dato real."
            if transition_measured else
            "Sobre dato real SIE: capacidad instalada + reclamaciones. La TRANSICIÓN "
            "(penetración renovable) queda como BRECHA en este período (sin dato de "
            "generación por tecnología). No se afirma transición sin dato."
        ),
    }
