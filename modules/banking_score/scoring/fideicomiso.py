"""Índice de Salud del Fideicomiso — health index for public trusts (fideicomisos).

Trusts are patrimonios autónomos (funds), NOT banks. They are very heterogeneous
(an operating toll-road concession vs a land-holding fund), so they are NOT placed on
the SDQ-AAA…D bank scale. Instead a 3-dimension health index on its own band scale:

  - Solvencia patrimonial : Patrimonio fideicomitido / Activos   (net-positive fund?)
  - Liquidez              : Activos líquidos / Pasivos circulantes (can meet near-term?)
  - Sostenibilidad        : Resultado del período (vs Activos)     (surplus, not deficit?)

Leverage is deliberately EXCLUDED from the score (high leverage is by design for
bond-financed infrastructure trusts). It is exposed as segment context instead.
Integrity: a dimension without its input is N/D (excluded, reweighted) — never faked.
Thresholds are v1 and calibratable.
"""
from typing import Any, Dict, Optional

from modules.banking_score.scoring.engine import _clamp, _safe_div

# Health bands (own scale — NOT SDQ-AAA…D).
HEALTH_BANDS = [
    (75.0, "Sólida"),
    (50.0, "Estable"),
    (30.0, "En vigilancia"),
    (0.0, "Frágil"),
]


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _lin(x: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 50.0
    return _clamp((x - lo) / (hi - lo) * 100.0)


def classify_segment(fields: Dict[str, Any]) -> str:
    """Classify a trust by nature (context for reading the score, not a score input).
    operativo (revenue-generating) · tenedor (asset-holding, ~no income) · desarrollo."""
    activos = _f(fields.get("activos_totales")) or 0.0
    ingresos = _f(fields.get("ingresos_operacionales")) or 0.0
    patrimonio = _f(fields.get("patrimonio_fideicomitido")) or 0.0
    if activos <= 0:
        return "indeterminado"
    income_ratio = ingresos / activos
    equity_ratio = patrimonio / activos
    if income_ratio >= 0.05:
        return "operativo"
    if equity_ratio >= 0.85 and income_ratio < 0.01:
        return "tenedor"
    return "desarrollo"


def compute_health(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the trust health index from extracted fields. Returns dimension
    scores (None = N/D), overall (reweighted over available), band and segment."""
    activos = _f(fields.get("activos_totales"))
    patrimonio = _f(fields.get("patrimonio_fideicomitido"))
    liquidos = _f(fields.get("activos_liquidos"))
    pasivos_circ = _f(fields.get("pasivos_circulantes"))
    resultado = _f(fields.get("resultado_periodo"))

    # Solvencia patrimonial — Patrimonio / Activos (net-positive fund).
    solvencia = None
    if activos and activos > 0 and patrimonio is not None:
        raw = patrimonio / activos * 100
        solvencia = round(_lin(raw, 0.0, 50.0), 2)

    # Liquidez — Activos líquidos / Pasivos circulantes.
    liquidez = None
    if liquidos is not None and pasivos_circ is not None and pasivos_circ > 0:
        raw = liquidos / pasivos_circ * 100
        liquidez = round(_lin(raw, 50.0, 200.0), 2)
    elif liquidos is not None and (pasivos_circ == 0):
        liquidez = 100.0  # liquid assets and no current liabilities → fully liquid

    # Sostenibilidad — Resultado del período / Activos (surplus vs deficit).
    sostenibilidad = None
    if resultado is not None and activos and activos > 0:
        raw = resultado / activos * 100
        sostenibilidad = round(_lin(raw, -2.0, 6.0), 2)

    dims = {"solvencia": solvencia, "liquidez": liquidez, "sostenibilidad": sostenibilidad}
    available = [v for v in dims.values() if v is not None]
    # Integrity: a single dimension is NOT a health verdict (e.g. solvencia=100 alone,
    # common in asset-holding trusts, would fake "Sólida"). Require ≥2 dimensions.
    if len(available) >= 2:
        overall = round(sum(available) / len(available), 2)
        band = _band(overall)
    else:
        overall = None
        band = "Datos insuficientes"

    return {
        "solvencia_score": solvencia,
        "liquidez_score": liquidez,
        "sostenibilidad_score": sostenibilidad,
        "overall_score": overall,
        "health_band": band,
        "segment": classify_segment(fields),
    }


def _band(overall: Optional[float]) -> str:
    if overall is None:
        return "N/D"
    for threshold, name in HEALTH_BANDS:
        if overall >= threshold:
            return name
    return "Frágil"
