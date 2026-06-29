"""Índice de Atractividad de Zonas Francas (IZF) — Eje Zonas Francas.

Funciones puras sobre dato real de la CNZFE (datos.gob.do). El sector de zonas francas
es NACIONAL (no hay firmas individuales); el índice mide su salud/atractividad para un
inversionista sobre 4 dimensiones, cada una puntuada por su ritmo de crecimiento (CAGR
3 años) contra un objetivo, igual que la adecuación de capacidad del IRSE:

  * **Dinamismo exportador**: CAGR de exportaciones (US$) vs ~5 %/año.
  * **Atracción de inversión**: CAGR de la inversión acumulada (US$) vs ~5 %/año.
  * **Generación de empleo**: CAGR de los empleos vs ~3 %/año.
  * **Productividad**: CAGR de exportaciones por empresa operando vs ~2 %/año.

El score pondera SOLO las dimensiones con dato (cobertura honesta); una serie sin ≥4
años de base no acredita su peso. Nunca fabrica precisión.
"""
from typing import Dict, List, Optional

W_EXPORTS = 0.30
W_INVESTMENT = 0.25
W_EMPLOYMENT = 0.20
W_PRODUCTIVITY = 0.25

# Objetivos de crecimiento anual (%/año) por dimensión — el ritmo que merece score pleno.
T_EXPORTS = 5.0
T_INVESTMENT = 5.0
T_EMPLOYMENT = 3.0
T_PRODUCTIVITY = 2.0

_CAGR_YEARS = 3  # ventana del CAGR


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
    base_year = latest - _CAGR_YEARS
    base = series.get(base_year)
    mw = series[latest]
    if base is None or base <= 0 or mw <= 0:
        return None
    return round(((mw / base) ** (1 / _CAGR_YEARS) - 1) * 100, 2)


def _dimension(series: Dict[int, float], target: float) -> Dict[str, Optional[float]]:
    """``{latest, cagr, score}`` para una serie vs su objetivo de crecimiento."""
    years = sorted(series)
    if not years:
        return {"latest": None, "cagr": None, "score": None}
    cagr = _cagr(series)
    score = round(_clamp(cagr / target * 100), 2) if cagr is not None else None
    return {"latest": round(series[years[-1]], 2), "cagr": cagr, "score": score}


def _series(vars_by_year: Dict[int, Dict[str, float]], field: str) -> Dict[int, float]:
    return {y: rec[field] for y, rec in vars_by_year.items() if rec.get(field) is not None}


def compute_free_zone_index(vars_by_year: Dict[int, Dict[str, float]]) -> Dict:
    """IZF desde las variables CNZFE por año. Pondera SOLO las dimensiones con dato; la
    cobertura es la fracción del índice medida."""
    exports = _series(vars_by_year, "exports_musd")
    investment = _series(vars_by_year, "investment_musd")
    jobs = _series(vars_by_year, "jobs")
    companies = _series(vars_by_year, "companies")
    # productividad = exportaciones por empresa operando, por año
    productivity = {y: exports[y] / companies[y] for y in exports
                    if companies.get(y) and companies[y] > 0}

    exp = _dimension(exports, T_EXPORTS)
    inv = _dimension(investment, T_INVESTMENT)
    emp = _dimension(jobs, T_EMPLOYMENT)
    prod = _dimension(productivity, T_PRODUCTIVITY)

    dims = {
        "export_dynamism": {"score": exp["score"], "weight": W_EXPORTS, "provenance": "real"},
        "investment_attraction": {"score": inv["score"], "weight": W_INVESTMENT, "provenance": "real"},
        "employment": {"score": emp["score"], "weight": W_EMPLOYMENT, "provenance": "real"},
        "productivity": {"score": prod["score"], "weight": W_PRODUCTIVITY, "provenance": "real"},
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

    years = sorted(vars_by_year)
    latest = vars_by_year.get(years[-1], {}) if years else {}
    return {
        "fz_score": score,
        "band": _band(score),
        "coverage": coverage,
        "dimensions": dims,
        "exports": exp,
        "investment": inv,
        "employment": emp,
        "productivity": prod,
        "levels": {  # contexto nominal del último año
            "companies": latest.get("companies"),
            "jobs": latest.get("jobs"),
            "exports_musd": latest.get("exports_musd"),
            "investment_musd": latest.get("investment_musd"),
            "parks": latest.get("parks"),
        },
    }
