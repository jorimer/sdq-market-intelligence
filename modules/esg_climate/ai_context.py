"""Compact AI context for the climate-resilience (IRC) narrative.

The narrative engine receives a SMALL, pre-digested context (IRC score, band, the
per-dimension contributions, the strongest/weakest dimension and the country's
position in the panel) — never the whole peer dataset — so prompts stay cheap and
focused. National (per country), mirrors :mod:`macro_political_risk.ai_context`.
"""
from typing import Any, Dict, List, Optional

from shared.narrative.derived import derived_figures

_DIM_LABELS = {
    "physical_risk": "Riesgo físico (huracán/clima)",
    "transition_risk": "Riesgo de transición (fósil/carbono)",
    "adaptive_capacity": "Capacidad adaptativa",
    "governance": "Gobernanza",
}
# Fuente que alimenta cada dimensión CUANDO su dato es real. La etiqueta es durable
# (la identidad del conector); el ESTADO no lo es — se lee del ``breakdown.sources``
# persistido en cada corrida (lección Hallazgo 7: la transición cae a rúbrica cada vez
# que el sync de Ember falla, así que "es dato real" no puede cablearse aquí).
_DIM_SOURCE = {
    "physical_risk": "HURDAT2 (NOAA) + ND-GAIN",
    "transition_risk": "Ember (electricidad)",
    "adaptive_capacity": "ND-GAIN",
    "governance": "ND-GAIN",
}

# Variables que componen cada dimensión (espejo de dimension_variables en la doctrina;
# solo para agregar la procedencia por dimensión desde el mapa por-variable).
_DIM_VARS = {
    "physical_risk": ("hurricane_exposure", "climate_sensitivity"),
    "transition_risk": ("fossil_dependence", "carbon_intensity"),
    "adaptive_capacity": ("adaptation_readiness", "economic_readiness"),
    "governance": ("governance_quality", "social_readiness"),
}


def _dim_provenance(key: str, var_sources: Dict[str, str]) -> str:
    """Procedencia de una dimensión desde el mapa por-variable de ESTA corrida.

    "real" si todas sus variables llegaron con dato vivo; "supuesto de casa (rúbrica
    declarada)" si ninguna; "parcial" si mezcla. Sin mapa (score viejo, pre-sources) →
    "sin registro de procedencia": honesto, nunca se asume real por omisión."""
    vars_ = _DIM_VARS.get(key, ())
    if not var_sources or not vars_:
        return "sin registro de procedencia"
    states = [str(var_sources.get(v, "")).strip().lower() for v in vars_]
    n_live = sum(1 for st in states if st == "live")
    if n_live == len(vars_):
        return "real"
    if n_live == 0:
        return "supuesto de casa (rúbrica declarada)"
    return f"parcial ({n_live}/{len(vars_)} variables con dato real)"


def _provenance_note(rows: List[Dict[str, Any]]) -> str:
    """Nota de procedencia derivada de las dimensiones de esta corrida."""
    real = [r["dimension"] for r in rows if r.get("provenance") == "real"]
    other = [(r["dimension"], r.get("provenance")) for r in rows
             if r.get("provenance") != "real"]
    if not other:
        return ("Las cuatro dimensiones del IRC llegan con dato real en esta corrida "
                "(fuentes: HURDAT2/NOAA, Ember, ND-GAIN). Panel Caribe/LatAm como "
                "conjunto de pares.")
    detail = "; ".join(f"{name}: {prov}" for name, prov in other)
    base = f"Dimensiones con dato real en esta corrida: {', '.join(real)}. " if real else ""
    return (f"{base}Atención a la procedencia — {detail}. Apóyate con firmeza solo en lo "
            f"real. Panel Caribe/LatAm como conjunto de pares.")


def climate_ai_context(
    entity_key: str,
    score: Dict[str, Any],
    country_name: Optional[str] = None,
    rank: Optional[int] = None,
    n_countries: Optional[int] = None,
    distribution: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compact context for one country's IRC climate-resilience assessment.

    *score* carries ``esg_score``, ``band`` and ``breakdown.dimensions``. Surfaces
    dimensions sorted by contribution + strongest/weakest, the real source per
    dimension, and the country's rank in the panel — so the narrative explains the
    score (distribution > average) and stays honest about provenance."""
    breakdown = score.get("breakdown") or {}
    dims = breakdown.get("dimensions") or {}
    var_sources = breakdown.get("sources") or {}
    rows: List[Dict[str, Any]] = []
    for key, d in dims.items():
        prov = _dim_provenance(key, var_sources)
        rows.append({
            "dimension": _DIM_LABELS.get(key, key),
            "score": d.get("score"),
            "weight": d.get("weight"),
            "contribution": d.get("contribution"),
            "source": _DIM_SOURCE.get(key, ""),
            # Estado de ESTA corrida, leído de lo persistido — no una afirmación cableada.
            "provenance": prov,
        })
    scored = [r for r in rows if r["score"] is not None]
    strongest = max(scored, key=lambda r: r["score"], default=None)
    weakest = min(scored, key=lambda r: r["score"], default=None)
    rows.sort(key=lambda r: (r["contribution"] is None, -(r["contribution"] or 0)))

    return {
        "entity_key": entity_key,
        "country_name": country_name,
        "period": score.get("period"),
        "irc_score": score.get("esg_score"),
        "band": score.get("band"),
        "direction": "mayor score = mayor resiliencia / menor riesgo climático",
        "rank": rank,
        "n_countries": n_countries,
        "distribution": distribution,         # mean/spread across the panel
        "dimensions": rows,
        "strongest_dimension": strongest,
        "weakest_dimension": weakest,
        # ── canónico (cerebro) ── (pares por rank/distribution en contexto)
        "score_global": score.get("esg_score"),
        "sub_componentes": [
            {"componente": r["dimension"], "score": r["score"], "peso": r["weight"]}
            for r in rows
        ],
        "cifras_derivadas": derived_figures(
            score=score.get("esg_score"),
            subcomponents=[{"componente": r["dimension"], "score": r["score"],
                            "peso": r["weight"]} for r in rows],
        ),
        # Nota GENERADA del estado real de la corrida — nunca afirmar "100% dato real"
        # en texto fijo: la dimensión de transición cae a rúbrica si su sync falla.
        "note": _provenance_note(rows),
    }
