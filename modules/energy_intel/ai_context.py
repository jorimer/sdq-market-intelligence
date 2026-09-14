"""Compact AI context for the electric-sector resilience (IRSE) narrative.

The narrative engine receives a SMALL, pre-digested context (IRSE score, band, the
two real dimensions with their contributions, and the declared transition gap) —
never raw series — so prompts stay cheap and honest about provenance. Module-local,
mirrors :mod:`trade_intel.ai_context`.
"""
from typing import Any, Dict, List, Optional
from shared.data.generation_client import GenerationMixClient
from shared.data.dgcp_ocds_client import DGCPOCDSClient
from shared.data.oc_seni_client import OCSENIClient
from shared.data.sie_client import SIEClient
from shared.narrative.atribucion import Fuente, bloque_de_atribucion


#: Los DOS emisores del eje, construidos de su conector (etiqueta + licencia juntas).
_SIE = Fuente.de_cliente(
    SIEClient, descripcion="SIE (capacidad instalada y reclamaciones), datos abiertos")
_ONE_GEN = Fuente.de_cliente(
    GenerationMixClient, descripcion="ONE (generación por tecnología), datos abiertos")

#: El feed MENSUAL del eje (Fase 5): el IMTE del Organismo Coordinador del SENI. No entra al
#: índice, que es anual; viaja solo a la sección del movimiento del mes.
FUENTE_OC_SENI = Fuente.de_cliente(
    OCSENIClient,
    descripcion="OC-SENI (Informe Mensual de Transacciones Económicas del mercado eléctrico)")

NOTA_DEL_FEED_IMTE = (
    "Las inyecciones son la energía que las centrales entregaron al sistema en el MES y los "
    "retiros la que salió de él: son flujos de energía, no capacidad instalada ni demanda de los "
    "usuarios finales. Los retiros de las distribuidoras son la energía que compraron las EDE en "
    "el mercado mayorista, no la que facturaron. Las pérdidas son de TRANSMISIÓN —la parte de lo "
    "inyectado que no se retiró— y no las pérdidas de distribución de las EDE, que son otra "
    "cifra y mucho mayor: no las confundas. El índice anual (IRSE) no usa este feed.")

#: El segundo feed mensual del eje (Fase 7): la obra pública que ADJUDICARON las unidades de compra
#: del sector eléctrico (EDE, ETED, Ministerio de Energía y Minas), del OCDS de la DGCP.
FUENTE_DGCP_ELECTRICA = Fuente.de_cliente(
    DGCPOCDSClient,
    descripcion="DGCP (obra pública adjudicada por las empresas del sector eléctrico, OCDS)")

NOTA_DEL_FEED_OBRA_ELECTRICA = (
    "Cuenta las obras que adjudicaron en el mes las empresas eléctricas del Estado y el Ministerio "
    "de Energía y Minas, identificadas por su unidad de compra. Son pocas por mes y un cero es un "
    "mes sin adjudicaciones, no un dato faltante. Adjudicar no es construir ni poner en servicio: "
    "no escribas que aumentó la capacidad o la red por una adjudicación.")


_DIM_LABELS = {
    "capacity_adequacy": "Adecuación de capacidad (parque instalado, SIE)",
    "service_quality": "Calidad de servicio (reclamaciones, SIE)",
    "energy_transition": "Transición energética (penetración renovable, ONE)",
}


def _financiamiento(perfil: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """El crédito y el costo laboral del sector, para el contexto del modelo.

    Delega en `shared.perfil_del_sector.contexto_del_perfil_del_sector`, que es el ÚNICO cuerpo:
    lo comparten los cuatro ejes cableados. Cuatro copias de la misma forma es como una se
    queda atrás, y este repo lo pagó con un serializador copiado a mano.
    """
    from shared.perfil_del_sector import contexto_del_perfil_del_sector
    return contexto_del_perfil_del_sector(perfil, "energia")


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
