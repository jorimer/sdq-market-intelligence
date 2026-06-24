"""Índice de Desarrollo Telecom (IDT) — Eje Telecomunicaciones.

Funciones puras sobre dato real de INDOTEL (boletín trimestral de indicadores):
  * **Penetración móvil/telefónica**: líneas totales por 100 habitantes.
  * **Penetración de internet**: suscripciones a internet por 100 habitantes.
  * **Calidad / banda ancha**: % de las suscripciones de internet que son banda ancha.

Las tres dimensiones salen del boletín real; el denominador poblacional es el censo
oficial de la ONE (dato real, no fabricado). El crecimiento de ingresos se reporta
como contexto (no se puntúa). Cobertura plena del índice (3/3 dims); la ANTIGÜEDAD
del boletín la refleja la frescura, no la cobertura.
"""
from typing import Dict, Optional

W_MOBILE = 0.30
W_INTERNET = 0.40
W_BROADBAND = 0.30


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


def compute_telecom_index(indicators: Dict[str, Optional[float]],
                          population: int) -> Dict:
    """IDT desde los indicadores INDOTEL + población. Pondera SOLO las dimensiones con
    dato (mín. 1); cobertura = peso medido / total."""
    lines = indicators.get("lines_total")
    internet = indicators.get("internet_total")
    broadband = indicators.get("broadband_total")
    pop = population if population and population > 0 else None

    mobile_pen = round(lines / pop * 100, 1) if (lines is not None and pop) else None
    internet_pen = round(internet / pop * 100, 1) if (internet is not None and pop) else None
    bb_share = (round(broadband / internet * 100, 1)
                if (broadband is not None and internet and internet > 0) else None)

    # Score por dimensión: penetración → min(pen, 100) (saturación = pleno);
    # banda ancha → el % directamente.
    mobile_score = round(_clamp(mobile_pen), 2) if mobile_pen is not None else None
    internet_score = round(_clamp(internet_pen), 2) if internet_pen is not None else None
    bb_score = round(_clamp(bb_share), 2) if bb_share is not None else None

    dims = {
        "mobile_penetration": {"score": mobile_score, "weight": W_MOBILE, "provenance": "real"},
        "internet_penetration": {"score": internet_score, "weight": W_INTERNET, "provenance": "real"},
        "broadband_quality": {"score": bb_score, "weight": W_BROADBAND, "provenance": "real"},
    }
    measured = [(d["score"], d["weight"]) for d in dims.values() if d["score"] is not None]
    total_w = sum(d["weight"] for d in dims.values())
    if measured:
        wsum = sum(w for _, w in measured)
        telecom_score = round(sum(s * w for s, w in measured) / wsum, 2)
        coverage = round(sum(w for _, w in measured) / total_w, 4)
    else:
        telecom_score, coverage = None, 0.0
    for d in dims.values():
        d["contribution"] = (round(d["score"] * d["weight"], 2)
                             if d["score"] is not None else None)

    rev_l, rev_p = indicators.get("revenue_latest"), indicators.get("revenue_prev")
    revenue_growth = (round((rev_l / rev_p - 1) * 100, 2)
                      if (rev_l is not None and rev_p and rev_p > 0) else None)

    return {
        "telecom_score": telecom_score,
        "band": _band(telecom_score),
        "coverage": coverage,
        "dimensions": dims,
        "metrics": {
            "mobile_penetration": mobile_pen, "internet_penetration": internet_pen,
            "broadband_share": bb_share, "lines_total": lines,
            "internet_total": internet, "broadband_total": broadband,
            "revenue_latest": rev_l, "revenue_growth": revenue_growth,
            "population": pop,
        },
    }
