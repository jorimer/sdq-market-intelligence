"""Índice de Construcción (ICC) — Eje Construcción.

Funciones puras sobre DOS fuentes reales y complementarias:

  * **MIVHED** (datos.gob.do) — licencias de construcción emitidas (transaccional): el
    indicador LÍDER del sector (el permiso precede a la obra).
  * **BCRD** — PIB de la construcción, crecimiento real interanual (cuentas nacionales,
    ``shared.data.bcrd_sectors``): la PRODUCCIÓN efectiva del sector (≈13.5% del VAB, el
    mayor sector único de la economía).

El sector construcción se lee a NIVEL NACIONAL (no hay firmas individuales); el índice
mide su coyuntura/capacidad para un inversionista o decisor público sobre 4 dimensiones:

  * **Producción del sector** (0.35): crecimiento real del PIB de construcción, promedio
    geométrico a 3 años, vs ~4 %/año. Señal de salida efectiva (BCRD).
  * **Pipeline de permisos** (0.35): CAGR a 3 años de los metros² licenciados, vs ~3 %/año.
    Señal líder de la actividad futura (MIVHED). Medida física (sin deflactar).
  * **Diversificación tipológica** (0.15): concentración de los permisos por tipología
    (HHI) — menor concentración = base de actividad más resiliente (MIVHED).
  * **Amplitud geográfica** (0.15): concentración de los permisos por provincia (HHI) —
    actividad más distribuida = menos dependiente de un solo mercado local (MIVHED).

El score pondera SOLO las dimensiones con dato (cobertura honesta): el pipeline necesita
≥4 años de m² para su CAGR; las primeras cosechas del MIVHED (desde 2022) solo acreditan
producción + diversificación. Nunca fabrica precisión.
"""
from typing import Any, Dict, List, Optional

W_PRODUCTION = 0.35
W_PIPELINE = 0.35
W_TYPOLOGY = 0.15
W_GEOGRAPHY = 0.15

# Objetivos de crecimiento anual (%/año) — el ritmo que merece score pleno.
T_PRODUCTION = 4.0   # crecimiento real del PIB de construcción "sano"
T_PIPELINE = 3.0     # expansión de m² licenciados que sostiene la actividad

_CAGR_YEARS = 3      # ventana del CAGR / del promedio de producción


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


def _production_dimension(growth_by_year: Dict[int, float],
                          period: int) -> Dict[str, Optional[float]]:
    """Promedio geométrico de los últimos ``_CAGR_YEARS`` crecimientos reales ≤ *period*.

    Suaviza el ruido cíclico (el boom post-pandemia y su normalización) sin fabricar una
    serie de nivel que el BCRD no expone por sector. Necesita ≥2 años con dato."""
    years = sorted(y for y in growth_by_year if y <= period and growth_by_year[y] is not None)
    if len(years) < 2:
        return {"latest": None, "avg_growth": None, "score": None}
    window = years[-_CAGR_YEARS:]
    factor = 1.0
    for y in window:
        factor *= (1.0 + growth_by_year[y] / 100.0)
    avg = round((factor ** (1.0 / len(window)) - 1.0) * 100, 2)
    score = round(_clamp(avg / T_PRODUCTION * 100), 2)
    return {"latest": round(growth_by_year[years[-1]], 2), "avg_growth": avg, "score": score}


def _pipeline_dimension(sqm_by_year: Dict[int, float],
                        period: int) -> Dict[str, Optional[float]]:
    """CAGR a 3 años de los m² licenciados (period-3 → period). Necesita el año base."""
    base = sqm_by_year.get(period - _CAGR_YEARS)
    mw = sqm_by_year.get(period)
    if base is None or mw is None or base <= 0 or mw <= 0:
        return {"latest": round(mw, 0) if mw else None, "cagr": None, "score": None}
    cagr = round(((mw / base) ** (1.0 / _CAGR_YEARS) - 1.0) * 100, 2)
    return {"latest": round(mw, 0), "cagr": cagr,
            "score": round(_clamp(cagr / T_PIPELINE * 100), 2)}


def _hhi(shares: Dict[str, float]) -> Optional[float]:
    total = sum(shares.values())
    if total <= 0:
        return None
    return round(sum((v / total) ** 2 for v in shares.values()) * 10000, 1)


def _typology_breakdown(detail: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
    """Desagregado por tipología — ``[{typology, permits, sqm, sqm_share}]`` — ordenado por
    m² licenciados descendente. Dato real del MIVHED: cuántos permisos y cuántos m² concentra
    cada tipo de construcción (p.ej. "Comercial y oficinas"), y su participación en los m²
    totales del año. Devuelve ``[]`` si el año no trae el desglose.

    Deliberadamente NO expone la columna "Inversión Total" por tipología: ese campo es un
    costo estándar derivado (m² × tarifa fija anual), por lo que su desglose por tipología es
    redundante con los m² y NO equivale al valor tasado de la ONE (ver
    ``shared.data.mivhed_client.parse_licenses``). La señal monetaria agregada ya vive en
    ``levels.investment_dop`` con su caveat de nominalidad."""
    rows: List[Dict[str, Any]] = []
    total_sqm = sum((d.get("sqm") or 0.0) for d in (detail or {}).values())
    for name, d in (detail or {}).items():
        sqm = round(d.get("sqm") or 0.0, 0)
        rows.append({
            "typology": name,
            "permits": int(d.get("permits") or 0),
            "sqm": sqm,
            "sqm_share": round(sqm / total_sqm * 100, 1) if total_sqm > 0 else None,
        })
    rows.sort(key=lambda r: r["sqm"], reverse=True)
    return rows


def _diversification_dimension(mix: Dict[str, float]) -> Dict[str, Optional[float]]:
    """Diversificación de una mezcla (tipología o provincia): menor HHI = mayor score.

    Normaliza el HHI entre su mínimo teórico (mezcla uniforme, 10000/n) y el máximo (un
    solo grupo, 10000). Necesita ≥2 grupos con dato."""
    present = {k: float(v) for k, v in mix.items() if v and v > 0}
    n = len(present)
    if n < 2:
        return {"hhi": None, "top": None, "top_share": None, "score": None}
    hhi = _hhi(present)
    total = sum(present.values())
    top = max(present, key=lambda k: present[k])
    top_share = round(present[top] / total * 100, 1)
    hhi_min = 10000.0 / n
    score = round(_clamp((1.0 - (hhi - hhi_min) / (10000.0 - hhi_min)) * 100), 2)
    return {"hhi": hhi, "top": top, "top_share": top_share, "score": score}


def compute_construction_index(
    licenses_by_year: Dict[int, Dict[str, Any]],
    growth_by_year: Dict[int, float],
    period: Optional[int] = None,
) -> Dict[str, Any]:
    """ICC desde las licencias MIVHED por año + el crecimiento real BCRD de la construcción.

    *period* es el año del índice (por defecto, el último año de ``licenses_by_year``). El
    caller debe pasar SOLO años completos en ``licenses_by_year`` (un trimestre suelto no
    es un año). Pondera SOLO las dimensiones con dato; la cobertura es la fracción medida."""
    years = sorted(licenses_by_year)
    if not years:
        return {"icc_score": None, "band": None, "coverage": 0.0, "dimensions": {},
                "production": {}, "pipeline": {}, "typology": {}, "geography": {}, "levels": {}}
    if period is None:
        period = years[-1]
    latest = licenses_by_year.get(period, {})

    sqm_by_year = {y: r["sqm"] for y, r in licenses_by_year.items()
                   if r.get("sqm") is not None}

    production = _production_dimension(growth_by_year, period)
    pipeline = _pipeline_dimension(sqm_by_year, period)
    typology = _diversification_dimension(latest.get("by_typology") or {})
    geography = _diversification_dimension(latest.get("by_province") or {})
    # El desglose por tipología (lista) se adjunta en el dict de salida (literal nuevo), no
    # sobre ``typology`` (tipado ``Dict[str, Optional[float]]``): así el cambio es neutral para
    # el baseline de mypy — no introduce ni resuelve violaciones.
    typology_out = {**typology,
                    "breakdown": _typology_breakdown(latest.get("by_typology_detail") or {})}

    dims = {
        "production": {"score": production["score"], "weight": W_PRODUCTION, "provenance": "real"},
        "pipeline": {"score": pipeline["score"], "weight": W_PIPELINE, "provenance": "real"},
        "typology_diversification": {"score": typology["score"], "weight": W_TYPOLOGY,
                                     "provenance": "real"},
        "geographic_breadth": {"score": geography["score"], "weight": W_GEOGRAPHY,
                               "provenance": "real"},
    }
    measured: List = [(d["score"], d["weight"]) for d in dims.values() if d["score"] is not None]
    total_w = sum(d["weight"] for d in dims.values())
    if measured:
        wsum = sum(w for _, w in measured)
        score = round(sum(s * w for s, w in measured) / wsum, 2)
        coverage = round(wsum / total_w, 4)
    else:
        score, coverage = None, 0.0
    for d in dims.values():
        d["contribution"] = (round(d["score"] * d["weight"], 2)
                             if d["score"] is not None else None)

    return {
        "icc_score": score,
        "band": _band(score),
        "coverage": coverage,
        "dimensions": dims,
        "production": production,
        "pipeline": pipeline,
        "typology": typology_out,
        "geography": geography,
        "levels": {  # contexto del año del índice
            "permits": latest.get("permits"),
            "sqm": round(latest.get("sqm"), 0) if latest.get("sqm") is not None else None,
            "investment_dop": (round(latest.get("investment"), 0)
                               if latest.get("investment") is not None else None),
            "prod_growth_latest": production["latest"],
            "prod_growth_3y": production["avg_growth"],
            "top_typology": typology["top"],
            "top_typology_share": typology["top_share"],
            "top_province": geography["top"],
            "top_province_share": geography["top_share"],
        },
    }
