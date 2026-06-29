"""Índice de Resiliencia del Sector Eléctrico (IRSE) — Eje Energía.

Funciones puras sobre dato real de la SIE (datos.gob.do):
  * **Adecuación de capacidad**: ritmo de expansión del parque instalado (MW) vs el
    crecimiento de demanda (~4 %/año). Más expansión sostenida = más holgura.
  * **Calidad de servicio**: backlog de reclamaciones (en proceso) en meses de
    recepción. Menos backlog = mejor servicio al usuario.

Tercera dimensión, antes BRECHA y ahora MEDIDA con dato real: la TRANSICIÓN
energética (penetración renovable). La generación por tecnología (% de la matriz)
se publica como dato abierto estructurado de la ONE (datos.gob.do) — ver
``shared/data/generation_client``. La penetración renovable (eólica+hidráulica+solar)
se puntúa contra la meta nacional de la Ley 57-07 (25 % renovable). El consumo de
combustible CKAN sigue excluido (quiebre de unidades 2018 → no se computa, nunca
falsa precisión). Con dato en las 3 dimensiones el índice alcanza cobertura plena;
si alguna falta, el score pondera SOLO lo medido (cobertura parcial honesta).
"""
from typing import Dict, List, Optional

# Pesos conceptuales del IRSE. Una dimensión sin dato NO acredita su peso: el score
# se reparte sobre las dimensiones con dato y la cobertura baja en proporción.
W_CAPACITY = 0.35
W_SERVICE = 0.30
W_TRANSITION = 0.35  # penetración renovable (ONE) — medida con dato real

DEMAND_GROWTH_TARGET = 4.0   # %/año — ritmo de demanda que la capacidad debe seguir
BACKLOG_FREE_MONTHS = 1.0    # ≤1 mes de backlog = servicio pleno
BACKLOG_ZERO_MONTHS = 9.0    # ≥9 meses de backlog = servicio colapsado
RENEWABLE_TARGET_PCT = 25.0  # meta nacional Ley 57-07 (25 % renovable) → score 100


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _band(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    if score >= 75:
        return "Fuerte"
    if score >= 60:
        return "Adecuado"
    if score >= 40:
        return "Vigilancia"
    return "Crítico"


def capacity_metrics(capacity_by_year: Dict[int, float]) -> Dict[str, Optional[float]]:
    """Nivel, crecimiento y score de adecuación desde {año: MW} (capacidad instalada).

    El score premia que la expansión (CAGR 3 años) siga el crecimiento de demanda
    (~4 %/año): ``score = min(100, CAGR/4 · 100)``. Sin ≥2 años → score None."""
    years = sorted(capacity_by_year)
    if not years:
        return {"capacity_mw": None, "yoy": None, "cagr_3y": None, "score": None}
    latest = years[-1]
    mw = capacity_by_year[latest]
    prev = capacity_by_year.get(latest - 1)
    yoy = round((mw / prev - 1) * 100, 2) if prev and prev > 0 else None
    base_year = latest - 3
    base = capacity_by_year.get(base_year)
    cagr = None
    score = None
    if base and base > 0:
        cagr = round(((mw / base) ** (1 / 3) - 1) * 100, 2)
        score = round(_clamp(cagr / DEMAND_GROWTH_TARGET * 100), 2)
    return {"capacity_mw": round(mw, 2), "yoy": yoy, "cagr_3y": cagr, "score": score}


def service_metrics(claims: List[Dict[str, object]],
                    months: int = 12) -> Dict[str, Optional[float]]:
    """Backlog y score de calidad de servicio desde las reclamaciones mensuales.

    ``backlog_months = en_proceso_último / recibidas_mensuales_promedio`` (trailing
    *months*). Score lineal: ≤1 mes → 100, ≥9 meses → 0. Sin dato → None."""
    rows = [r for r in claims if r.get("recibidas") is not None]
    if not rows:
        return {"backlog": None, "backlog_months": None, "avg_received": None, "score": None}
    window = rows[-months:]
    received = [float(r["recibidas"]) for r in window if r.get("recibidas") is not None]
    avg_received = sum(received) / len(received) if received else None
    backlog = next((float(r["en_proceso"]) for r in reversed(rows)
                    if r.get("en_proceso") is not None), None)
    if not avg_received or avg_received <= 0 or backlog is None:
        return {"backlog": backlog, "backlog_months": None,
                "avg_received": round(avg_received, 1) if avg_received else None, "score": None}
    backlog_months = backlog / avg_received
    span = BACKLOG_ZERO_MONTHS - BACKLOG_FREE_MONTHS
    score = round(_clamp(100 - max(0.0, backlog_months - BACKLOG_FREE_MONTHS) / span * 100), 2)
    return {"backlog": round(backlog, 0), "backlog_months": round(backlog_months, 2),
            "avg_received": round(avg_received, 1), "score": score}


def transition_metrics(
    renewable_share_by_year: Optional[Dict[int, float]]) -> Dict[str, Optional[float]]:
    """Penetración renovable y score de transición desde {año: % renovable}.

    Toma el último año con dato y puntúa contra la meta nacional (Ley 57-07, 25 %):
    ``score = min(100, share/25 · 100)``. Reporta también la variación vs 5 años
    antes (señal de avance). Sin dato → score None (la dimensión vuelve a ser brecha)."""
    if not renewable_share_by_year:
        return {"renewable_share": None, "delta_5y": None, "year": None, "score": None}
    years = sorted(renewable_share_by_year)
    latest = years[-1]
    share = renewable_share_by_year[latest]
    base = renewable_share_by_year.get(latest - 5)
    delta = round(share - base, 2) if base is not None else None
    score = round(_clamp(share / RENEWABLE_TARGET_PCT * 100), 2)
    return {"renewable_share": round(share, 2), "delta_5y": delta,
            "year": latest, "score": score}


def compute_energy_index(capacity_by_year: Dict[int, float],
                         claims: List[Dict[str, object]],
                         renewable_share_by_year: Optional[Dict[int, float]] = None) -> Dict:
    """IRSE desde capacidad + reclamaciones + penetración renovable (dato real). El
    score pondera SOLO las dimensiones con dato (mín. 1); una dimensión sin dato queda
    como brecha y baja la cobertura."""
    cap = capacity_metrics(capacity_by_year)
    svc = service_metrics(claims)
    tra = transition_metrics(renewable_share_by_year)

    dims = {
        "capacity_adequacy": {"score": cap["score"], "weight": W_CAPACITY, "provenance": "real"},
        "service_quality": {"score": svc["score"], "weight": W_SERVICE, "provenance": "real"},
        "energy_transition": {
            "score": tra["score"], "weight": W_TRANSITION,
            "provenance": "real" if tra["score"] is not None else "brecha"},
    }
    measured = [(d["score"], d["weight"]) for d in dims.values() if d["score"] is not None]
    total_w = sum(d["weight"] for d in dims.values())
    if measured:
        wsum = sum(w for _, w in measured)
        energy_score = round(sum(s * w for s, w in measured) / wsum, 2)
        coverage = round(sum(w for _, w in measured) / total_w, 4)
    else:
        energy_score, coverage = None, 0.0
    for d in dims.values():
        d["contribution"] = (round(d["score"] * d["weight"], 2)
                             if d["score"] is not None else None)

    return {
        "energy_score": energy_score,
        "band": _band(energy_score),
        "coverage": coverage,
        "dimensions": dims,
        "capacity": cap,
        "service": svc,
        "transition": tra,
    }
