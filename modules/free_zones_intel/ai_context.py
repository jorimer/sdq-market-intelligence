"""Compact AI context for the free-zone attractiveness (IZF) narrative.

The narrative engine receives a SMALL, pre-digested context (IZF score, band, the
dimensions with their CAGR/contribution, and the latest-year levels) — never raw
series — so prompts stay cheap and honest about provenance. Module-local, mirrors
:mod:`energy_intel.ai_context`.
"""
from typing import Any, Dict, List, Optional
from shared.data.cnzfe_client import CNZFEClient
from shared.narrative.atribucion import Fuente, bloque_de_atribucion


#: Emisor único del eje, construido de su conector.
_CNZFE = Fuente.de_cliente(
    CNZFEClient, descripcion="CNZFE (Consejo Nacional de Zonas Francas), datos abiertos")


_DIM_LABELS = {
    "export_dynamism": "Dinamismo exportador (CAGR exportaciones, CNZFE)",
    "investment_attraction": "Atracción de inversión (CAGR inversión acumulada, CNZFE)",
    "employment": "Generación de empleo (CAGR empleos, CNZFE)",
    "productivity": "Productividad (CAGR exportaciones por empresa, CNZFE)",
}


def _financiamiento(perfil: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """El crédito y el costo laboral del sector, para el contexto del modelo.

    Delega en `shared.perfil_del_sector.contexto_de_financiamiento`, que es el ÚNICO cuerpo:
    lo comparten los cuatro ejes cableados. Cuatro copias de la misma forma es como una se
    queda atrás, y este repo lo pagó con un serializador copiado a mano.
    """
    from shared.perfil_del_sector import contexto_de_financiamiento
    return contexto_de_financiamiento(perfil, "zonas_francas")


def free_zones_ai_context(index: Dict[str, Any], period: str,
                          perfil: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compact context for the free-zone sector attractiveness assessment.

    *index* is the ``compute_free_zone_index`` output. Surfaces the dimensions (score +
    CAGR + contribution) and the latest-year levels so the narrative explains the score
    and stays honest about provenance/coverage."""
    dims = index.get("dimensions") or {}
    rows: List[Dict[str, Any]] = []
    # cada dimensión tiene sus métricas (cagr, latest) bajo una clave canónica
    _METRIC_KEY = {"export_dynamism": "exports", "investment_attraction": "investment",
                   "employment": "employment", "productivity": "productivity"}
    for key, d in dims.items():
        m = index.get(_METRIC_KEY.get(key, "")) or {}
        rows.append({
            "dimension": _DIM_LABELS.get(key, key),
            "score": d.get("score"),
            "weight": d.get("weight"),
            "contribution": d.get("contribution"),
            "cagr_pct": m.get("cagr"),
            "provenance": d.get("provenance"),
        })
    levels = index.get("levels") or {}
    return {
        "period": period,
        "izf_score": index.get("fz_score"),
        "band": index.get("band"),
        "coverage": index.get("coverage"),
        "direction": "mayor score = sector de zonas francas más atractivo/dinámico",
        "dimensions": rows,
        "companies": levels.get("companies"),
        "jobs": levels.get("jobs"),
        "exports_musd": levels.get("exports_musd"),
        "investment_musd": levels.get("investment_musd"),
        "parks": levels.get("parks"),
        "score_global": index.get("fz_score"),
        **_financiamiento(perfil),
        **bloque_de_atribucion(_CNZFE),
        "note": ("Sobre dato real CNZFE: fundamentos anuales del sector de zonas francas "
                 "(exportaciones, inversión acumulada, empleos, empresas). Índice de "
                 "dinamismo por CAGR vs objetivo. Agregado nacional, sin desglose por "
                 "sub-sector industrial ni validación retrospectiva de resultados."),
    }
