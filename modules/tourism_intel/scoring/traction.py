"""Índice de Tracción Turística (ITT) — Eje Turismo.

Funciones puras sobre dato real de la ONE (datos.gob.do, llegadas vía aérea). El sector
turismo se lee a NIVEL NACIONAL (no hay firmas individuales); el índice mide la tracción
de demanda del destino RD para un inversionista sobre 4 dimensiones:

  * **Demanda total**: CAGR a 3 años de las llegadas de no residentes vs ~5 %/año.
  * **Demanda extranjera**: CAGR a 3 años de los extranjeros no residentes (turista
    internacional puro, sin la diáspora) vs ~5 %/año.
  * **Resiliencia / recuperación**: nivel de llegadas actuales vs el pico pre-pandemia
    (≤2019); 100 % = recuperación plena (se topa en pleno, lo que excede es dinamismo).
  * **Diversificación de mercados**: concentración por región emisora (HHI) — menor
    concentración = base de demanda más resiliente. Penaliza la dependencia de un mercado.

El score pondera SOLO las dimensiones con dato (cobertura honesta): una serie sin base de
≥4 años para el CAGR, o sin un año pre-2020 para la recuperación, no acredita su peso.
Nunca fabrica precisión.
"""
from typing import Dict, List, Optional

W_TOTAL_DEMAND = 0.30
W_FOREIGN_DEMAND = 0.25
W_RECOVERY = 0.25
W_DIVERSIFICATION = 0.20

# Objetivos de crecimiento anual (%/año) — el ritmo que merece score pleno.
T_TOTAL = 5.0
T_FOREIGN = 5.0

_CAGR_YEARS = 3            # ventana del CAGR
_PREPANDEMIC_MAX_YEAR = 2019  # referencia de recuperación (pico ≤ este año)


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


def _cagr(series: Dict[int, float]) -> Optional[float]:
    """CAGR % de los últimos ``_CAGR_YEARS`` años de *series* ({año: valor})."""
    years = sorted(series)
    if len(years) < 2:
        return None
    latest = years[-1]
    base = series.get(latest - _CAGR_YEARS)
    mw = series[latest]
    if base is None or base <= 0 or mw <= 0:
        return None
    return round(((mw / base) ** (1 / _CAGR_YEARS) - 1) * 100, 2)


def _growth_dimension(series: Dict[int, float], target: float) -> Dict[str, Optional[float]]:
    """``{latest, cagr, score}`` para una serie de demanda vs su objetivo de crecimiento."""
    years = sorted(series)
    if not years:
        return {"latest": None, "cagr": None, "score": None}
    cagr = _cagr(series)
    score = round(_clamp(cagr / target * 100), 2) if cagr is not None else None
    return {"latest": round(series[years[-1]], 0), "cagr": cagr, "score": score}


def _recovery_dimension(nonresident: Dict[int, float]) -> Dict[str, Optional[float]]:
    """Nivel actual vs el pico pre-pandemia (≤2019). Recuperación plena (≥100 %) = score 100."""
    years = sorted(nonresident)
    if not years:
        return {"latest": None, "peak": None, "ratio": None, "peak_year": None, "score": None}
    pre = {y: nonresident[y] for y in years if y <= _PREPANDEMIC_MAX_YEAR}
    if not pre:
        return {"latest": round(nonresident[years[-1]], 0), "peak": None,
                "ratio": None, "peak_year": None, "score": None}
    peak_year = max(pre, key=lambda y: pre[y])
    peak = pre[peak_year]
    latest = nonresident[years[-1]]
    if peak <= 0:
        return {"latest": round(latest, 0), "peak": round(peak, 0),
                "ratio": None, "peak_year": peak_year, "score": None}
    ratio = round(latest / peak * 100, 1)
    return {"latest": round(latest, 0), "peak": round(peak, 0), "ratio": ratio,
            "peak_year": peak_year, "score": round(_clamp(ratio), 2)}


def _hhi(shares: Dict[str, float]) -> Optional[float]:
    """HHI (0..10000) de la mezcla por región emisora."""
    total = sum(shares.values())
    if total <= 0:
        return None
    return round(sum((v / total) ** 2 for v in shares.values()) * 10000, 1)


def _diversification_dimension(regions: Dict[str, float]) -> Dict[str, Optional[float]]:
    """Diversificación por región emisora: menor HHI = mayor score.

    Normaliza el HHI entre su mínimo teórico (mezcla perfectamente uniforme, 10000/n) y
    el máximo (un solo mercado, 10000). Necesita ≥2 regiones con dato."""
    present = {k: v for k, v in regions.items() if v and v > 0}
    n = len(present)
    if n < 2:
        return {"hhi": None, "top_region": None, "top_share": None, "score": None}
    hhi = _hhi(present)
    total = sum(present.values())
    top_region = max(present, key=lambda k: present[k])
    top_share = round(present[top_region] / total * 100, 1)
    hhi_min = 10000.0 / n
    score = round(_clamp((1.0 - (hhi - hhi_min) / (10000.0 - hhi_min)) * 100), 2)
    return {"hhi": hhi, "top_region": top_region, "top_share": top_share, "score": score}


def _series(arrivals_by_year: Dict[int, Dict[str, object]], field: str) -> Dict[int, float]:
    out: Dict[int, float] = {}
    for y, rec in arrivals_by_year.items():
        v = rec.get(field)
        if isinstance(v, (int, float)) and v is not None:
            out[y] = float(v)
    return out


def compute_tourism_index(arrivals_by_year: Dict[int, Dict[str, object]]) -> Dict:
    """ITT desde las llegadas por año (salida de ``parse_arrivals``). Pondera SOLO las
    dimensiones con dato; la cobertura es la fracción del índice medida."""
    nonresident = _series(arrivals_by_year, "nonresident")
    foreign = _series(arrivals_by_year, "foreign")
    years = sorted(arrivals_by_year)
    latest_regions: Dict[str, float] = {}
    if years:
        lr = arrivals_by_year[years[-1]].get("regions") or {}
        latest_regions = {str(k): float(v) for k, v in lr.items()  # type: ignore[union-attr]
                          if isinstance(v, (int, float))}

    total = _growth_dimension(nonresident, T_TOTAL)
    foreign_d = _growth_dimension(foreign, T_FOREIGN)
    recovery = _recovery_dimension(nonresident)
    diversification = _diversification_dimension(latest_regions)

    dims = {
        "total_demand": {"score": total["score"], "weight": W_TOTAL_DEMAND, "provenance": "real"},
        "foreign_demand": {"score": foreign_d["score"], "weight": W_FOREIGN_DEMAND, "provenance": "real"},
        "recovery": {"score": recovery["score"], "weight": W_RECOVERY, "provenance": "real"},
        "diversification": {"score": diversification["score"], "weight": W_DIVERSIFICATION, "provenance": "real"},
    }
    measured: List = [(d["score"], d["weight"]) for d in dims.values() if d["score"] is not None]
    total_w = sum(d["weight"] for d in dims.values())
    if measured:
        wsum = sum(w for _, w in measured)
        score = round(sum(s * w for s, w in measured) / wsum, 2)
        coverage = round(sum(w for _, w in measured) / total_w, 4)
    else:
        score, coverage = None, 0.0
    for d in dims.values():
        d["contribution"] = (round(d["score"] * d["weight"], 2)
                             if d["score"] is not None else None)

    latest = arrivals_by_year.get(years[-1], {}) if years else {}
    return {
        "itt_score": score,
        "band": _band(score),
        "coverage": coverage,
        "dimensions": dims,
        "total_demand": total,
        "foreign_demand": foreign_d,
        "recovery": recovery,
        "diversification": diversification,
        "levels": {  # contexto nominal del último año
            "nonresident": latest.get("nonresident"),
            "foreign": latest.get("foreign"),
            "top_region": diversification["top_region"],
            "top_share": diversification["top_share"],
            "hhi": diversification["hhi"],
        },
    }
