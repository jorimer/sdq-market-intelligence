"""Compact AI context for the tourism-traction (ITT) narrative.

The narrative engine receives a SMALL, pre-digested context (ITT score, band, the
dimensions with their CAGR/contribution, and the latest-year levels) — never raw
series — so prompts stay cheap and honest about provenance. Module-local, mirrors
:mod:`free_zones_intel.ai_context`.
"""
from typing import Any, Dict, List, Optional
from shared.data.bcrd_llegadas_client import BCRDLlegadasClient
from shared.data.tourism_arrivals_client import TourismArrivalsClient
from shared.narrative.atribucion import Fuente, bloque_de_atribucion


#: Emisor único del eje, construido de su conector.
_ONE = Fuente.de_cliente(
    TourismArrivalsClient,
    descripcion="ONE (Oficina Nacional de Estadística), llegadas vía aérea, datos abiertos")

#: El feed MENSUAL del eje (Fase 6): la llegada de no residentes del BCRD. No entra al índice,
#: que es anual y se arma con la ONE; viaja solo a la sección del movimiento del mes.
FUENTE_BCRD_LLEGADAS = Fuente.de_cliente(
    BCRDLlegadasClient, descripcion="BCRD (llegada mensual de pasajeros no residentes vía aérea)")

NOTA_DEL_FEED_LLEGADAS = (
    "Son personas no residentes que LLEGARON por vía aérea en el mes: un flujo con estación "
    "marcada, que se mide contra el MISMO mes del año anterior y nunca contra el mes previo. "
    "Los dominicanos no residentes son la diáspora que visita, no turistas extranjeros: no los "
    "sumes a los extranjeros como si fueran el mismo público. Las cifras del año en curso son "
    "preliminares del BCRD. Llegar no es ocupar una habitación ni gastar: no escribas sobre "
    "ocupación ni divisas a partir de esta serie.")

#: Qué publica HOY el Ministerio de Turismo sobre ocupación, verificado el 2026-09-14. Antes el
#: texto decía que la ocupación «solo vive en PDFs, sin serie limpia»: era cierto del BCRD, que
#: la discontinuó en 2018-2019, pero MITUR publica los indicadores en el tablero de SITUR.
OCUPACION_HOTELERA_VERIFICADA_EL = "2026-09-14"


_DIM_LABELS = {
    "total_demand": "Demanda total (CAGR llegadas de no residentes, ONE)",
    "foreign_demand": "Demanda extranjera (CAGR extranjeros no residentes, ONE)",
    "recovery": "Resiliencia / recuperación (nivel vs pico pre-pandemia, ONE)",
    "diversification": "Diversificación de mercados (HHI por región emisora, ONE)",
}
# cada dimensión guarda sus métricas bajo una clave canónica
_METRIC_KEY = {"total_demand": "total_demand", "foreign_demand": "foreign_demand",
               "recovery": "recovery", "diversification": "diversification"}


def _financiamiento(perfil: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """El crédito y el costo laboral del sector, para el contexto del modelo.

    Delega en `shared.perfil_del_sector.contexto_del_perfil_del_sector`, que es el ÚNICO cuerpo:
    lo comparten los cuatro ejes cableados. Cuatro copias de la misma forma es como una se
    queda atrás, y este repo lo pagó con un serializador copiado a mano.
    """
    from shared.perfil_del_sector import contexto_del_perfil_del_sector
    return contexto_del_perfil_del_sector(perfil, "turismo")


def tourism_ai_context(index: Dict[str, Any], period: str,
                       perfil: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compact context for the tourism-sector traction assessment.

    *index* is the ``compute_tourism_index`` output. Surfaces the dimensions (score +
    metric + contribution) and the latest-year levels so the narrative explains the
    score and stays honest about provenance/coverage."""
    dims = index.get("dimensions") or {}
    rows: List[Dict[str, Any]] = []
    for key, d in dims.items():
        m = index.get(_METRIC_KEY.get(key, "")) or {}
        rows.append({
            "dimension": _DIM_LABELS.get(key, key),
            "score": d.get("score"),
            "weight": d.get("weight"),
            "contribution": d.get("contribution"),
            "cagr_pct": m.get("cagr"),       # demanda total/extranjera
            "recovery_pct": m.get("ratio"),  # recuperación
            # sujeto-ok: fila de dimensión, ya rotulada con `dimension`
            "hhi": m.get("hhi"),             # diversificación
            "provenance": d.get("provenance"),
        })
    levels = index.get("levels") or {}
    recovery = index.get("recovery") or {}
    diversification = index.get("diversification") or {}
    return {
        "period": period,
        "itt_score": index.get("itt_score"),
        "band": index.get("band"),
        "coverage": index.get("coverage"),
        "direction": "mayor score = destino turístico con más tracción de demanda y resiliencia",
        "dimensions": rows,
        "nonresident_arrivals": levels.get("nonresident"),
        "foreign_arrivals": levels.get("foreign"),
        "top_origin_region": diversification.get("top_region"),
        "top_origin_share_pct": diversification.get("top_share"),
        "recovery_vs_prepandemic_pct": recovery.get("ratio"),
        "prepandemic_peak_year": recovery.get("peak_year"),
        "score_global": index.get("itt_score"),
        **_financiamiento(perfil),
        **bloque_de_atribucion(_ONE),
        "note": ("Sobre dato real ONE: llegadas anuales de no residentes vía aérea por "
                 "mercado de origen. Índice de tracción de DEMANDA (volumen, recuperación, "
                 "diversificación de mercados). NO cubre oferta hotelera, ocupación, ni "
                 "ingresos por turismo (divisas): este índice no los ingiere; no los "
                 "inventes. Sin validación retrospectiva de resultados."),
    }
