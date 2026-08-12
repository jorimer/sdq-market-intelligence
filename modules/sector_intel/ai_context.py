"""Compact AI context for the sector attractiveness (IAI) narrative.

The narrative engine receives a SMALL, pre-digested context (IAI score, band,
the per-dimension contributions, the strongest/weakest dimension and the real-vs-
rubric provenance) — never the whole peer dataset — so prompts stay cheap and
focused (plan §5.2). Module-local, mirrors :mod:`macro_political_risk.ai_context`.
"""
from typing import Any, Dict, List, Optional

from shared.narrative.derived import derived_figures

_DIM_LABELS = {
    "sector": "Sector (tamaño y crecimiento, BCRD)",
    "macro": "Exposición macro (contrato macro→sectorial)",
    "business": "Entorno de negocios",
    "talent": "Talento y mano de obra",
    "regulation": "Regulatoria",
}
# Dimensions sourced from real data today; the rest are declared rubric.
_LIVE_DIMS = {"sector", "macro"}


def economic_structure_ai_context(structure: Dict[str, Any]) -> Dict[str, Any]:
    """Compact context for the aggregate economic-structure narrative.

    *structure* is the ``get_economic_structure`` output. Surfaces the structural weight
    ranking, the growth drivers vs drags (by contribution) and the aggregate VA growth, so
    the narrative explains which sectors move the economy — distinguishing SIZE (weight)
    from CONTRIBUTION (weight × growth). Honest: real BCRD value-added, no synthetic score."""
    def _slim(r: Dict[str, Any]) -> Dict[str, Any]:
        return {"sector": r.get("sector"), "weight_pct": r.get("weight"),
                "growth_pct": r.get("growth"), "contribution_pp": r.get("contribution"),
                # sujeto-ok: fila ya rotulada con `sector`; «of_growth» nombra el total
                "share_of_growth": r.get("contribution_share")}

    sectors = structure.get("sectors") or []
    return {
        "period": structure.get("period"),
        "total_va_growth_pct": structure.get("total_va_growth"),
        "coverage": structure.get("coverage"),
        # HHI sobre el peso de los SECTORES en el Valor Agregado. La clave interna conserva
        # su nombre; la que ve el modelo nombra la población.
        "concentration_hhi_sectors": structure.get("concentration_hhi"),
        "n_sectors": structure.get("n_sectors"),
        "direction": ("peso = importancia estructural (share del Valor Agregado); "
                      "contribución = peso × crecimiento = aporte real al crecimiento"),
        "structure_top_weight": [_slim(r) for r in sectors[:6]],
        "growth_drivers": [_slim(r) for r in (structure.get("drivers") or [])[:6]],
        "growth_drags": [_slim(r) for r in (structure.get("drags") or [])],
        "source": structure.get("source"),
        "note": ("Real: BCRD PIB por sectores de origen (Valor Agregado base 2018). Mide "
                 "importancia económica y contribución al crecimiento — NO valor exportado "
                 "(esa es otra lente, donde joyería/oro lideran) ni atractividad (IAI). "
                 "Agregado nacional anual; sin score sintético. Si una cifra no está, dilo."),
    }


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

    # Forma canónica para la ruta cerebro: score_global + sub_componentes (con peso) +
    # cifras_derivadas (precompute compartido). Sin serie ni pares en este eje → el
    # precompute solo emite aportes/gaps/superlativos de dimensión.
    subcomp = [{"componente": r["dimension"], "score": r["score"], "peso": r["weight"],
                "procedencia": r["provenance"]} for r in rows]
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
        # ── canónico (cerebro) ──
        "score_global": latest.get("iai_score"),
        "sub_componentes": subcomp,
        "cifras_derivadas": derived_figures(
            score=latest.get("iai_score"),
            subcomponents=[{"componente": s["componente"], "score": s["score"],
                            "peso": s["peso"]} for s in subcomp],
        ),
    }
