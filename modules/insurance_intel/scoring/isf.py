"""Índice de Solidez de Aseguradora (ISF) — insurer solidity index.

Mirrors the pension ISA: a 0-100 band index over REAL public SIS data (audited
statements por cía), NOT a credit rating. Five dimensions (weights sum to 1.0),
each scored 0-100 by a HYBRID of an absolute band (0.5) + peer min-max (0.5) so the
score is both anchored and discriminating; the overall is the weighted mean over the
PRESENT dimensions, with ``coverage`` = share of the declared methodology backed by
real data.

    solvencia         0.35  patrimonio / activos                 higher=better
    siniestralidad    0.20  siniestros / primas (loss ratio)     lower ratio=better
    liquidez          0.15  activos líquidos / reservas técnicas  higher=better
    escala            0.15  activos totales (log)                 higher=better
    resultado_tecnico 0.15  (ingresos − gastos) / primas          higher=better

With audited statements ingested, coverage ≈ 1.0 → the ISF emits an ABSOLUTE band
(Sólida/Adecuada/En vigilancia/Frágil) besides ranking. Missing inputs → the
dimension is a declared gap (present=False), never fabricated.
"""
import math
from statistics import pstdev  # noqa: F401  (reserved for future dispersion use)
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

# Dimension spec: weight, direction, and absolute anchors (worst→0, best→100),
# calibrated to the real 33-insurer distribution (2024 audited).
DIMENSIONS = [
    {"key": "solvencia", "label": "Solvencia (patrimonio/activos)", "weight": 0.35,
     "direction": "higher", "lo": 0.10, "hi": 0.40, "log": False},
    {"key": "siniestralidad", "label": "Siniestralidad (loss ratio)", "weight": 0.20,
     "direction": "lower", "lo": 0.85, "hi": 0.25, "log": False},
    {"key": "liquidez", "label": "Liquidez (líquidos/reservas técnicas)", "weight": 0.15,
     "direction": "higher", "lo": 0.40, "hi": 2.00, "log": False},
    {"key": "escala", "label": "Escala (activos totales)", "weight": 0.15,
     "direction": "higher", "lo": 5e8, "hi": 3.5e10, "log": True},
    {"key": "resultado_tecnico", "label": "Resultado técnico (sobre primas)", "weight": 0.15,
     "direction": "higher", "lo": -0.05, "hi": 0.20, "log": False},
]
_WABS = 0.5  # hybrid weight of the absolute band vs. peer min-max
_MIN_COVERAGE = 0.50
_BANDS = [(75, "Sólida"), (60, "Adecuada"), (45, "En vigilancia"), (0, "Frágil")]


def band_for(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    for threshold, name in _BANDS:
        if score >= threshold:
            return name
    return "Frágil"


def _absolute(raw: float, spec: Dict) -> float:
    lo, hi = spec["lo"], spec["hi"]
    if spec.get("log"):
        raw = math.log10(max(raw, 1.0))
        lo, hi = math.log10(lo), math.log10(hi)
    frac = (raw - lo) / (hi - lo) if hi != lo else 0.5
    return max(0.0, min(1.0, frac)) * 100


def _minmax(raw: float, peers: List[float], direction: str) -> Optional[float]:
    if len(peers) < 2:
        return None
    lo, hi = min(peers), max(peers)
    if hi == lo:
        return 50.0
    frac = (raw - lo) / (hi - lo)
    if direction == "lower":
        frac = 1 - frac
    return max(0.0, min(1.0, frac)) * 100


def _raw_metric(fin: Dict[str, Any], key: str) -> Optional[float]:
    """Derive a dimension's raw ratio from an insurer's financials dict."""
    g = fin.get
    if key == "solvencia":
        return (g("patrimonio") / g("activos_totales")) if g("activos_totales") else None
    if key == "siniestralidad":
        return (g("siniestros_pagados") / g("primas_suscritas")) if g("primas_suscritas") else None
    if key == "liquidez":
        return (g("activos_liquidos") / g("reservas_tecnicas")) if g("reservas_tecnicas") else None
    if key == "escala":
        return g("activos_totales")
    if key == "resultado_tecnico":
        ing, gas, pri = g("ingresos_totales"), g("gastos_totales"), g("primas_suscritas")
        return ((ing - gas) / pri) if (ing is not None and gas is not None and pri) else None
    return None


def score_insurers(financials: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pure ISF scorer over a list of insurer financials dicts (testable, no DB).

    Each dict has ``slug``, ``name``, ``period`` + the raw figures (patrimonio,
    activos_totales, primas_suscritas, siniestros_pagados, reservas_tecnicas,
    activos_liquidos, ingresos_totales, gastos_totales)."""
    # Peer pools per dimension (for min-max), over insurers where the raw exists.
    raws: Dict[str, Dict[str, Optional[float]]] = {}
    for fin in financials:
        raws[fin["slug"]] = {d["key"]: _raw_metric(fin, d["key"]) for d in DIMENSIONS}
    pools = {d["key"]: [raws[s][d["key"]] for s in raws if raws[s][d["key"]] is not None]
             for d in DIMENSIONS}

    total_weight = sum(d["weight"] for d in DIMENSIONS)
    out: List[Dict[str, Any]] = []
    for fin in financials:
        slug = fin["slug"]
        dims: List[Dict[str, Any]] = []
        num = wsum = 0.0
        for d in DIMENSIONS:
            raw = raws[slug][d["key"]]
            present = raw is not None
            score = None
            if present:
                a = _absolute(raw, d)
                mm = _minmax(raw, pools[d["key"]], d["direction"])
                score = round(_WABS * a + (1 - _WABS) * mm, 1) if mm is not None else round(a, 1)
                num += score * d["weight"]
                wsum += d["weight"]
            dims.append({"key": d["key"], "label": d["label"], "weight": d["weight"],
                         "raw": None if raw is None else round(raw, 4),
                         "score": score, "provenance": "real", "present": present})
        coverage = round(wsum / total_weight, 4) if total_weight else 0.0
        overall = round(num / wsum, 1) if wsum and coverage >= _MIN_COVERAGE else None
        out.append({
            "slug": slug, "name": fin.get("name", slug), "period": fin.get("period"),
            "overall_score": overall, "band": band_for(overall) if coverage >= 0.99 else None,
            "coverage": coverage, "dimensions": dims,
            "score_kind": "absolute" if coverage >= 0.99 else "relative",
        })
    out.sort(key=lambda r: (r["overall_score"] is not None, r["overall_score"] or 0), reverse=True)
    return out


def _load_financials(db: Session) -> List[Dict[str, Any]]:
    """Assemble each insurer's latest per-entity figures from ``insurance_series``."""
    from modules.insurance_intel.models.models import InsuranceEntity, InsuranceSeries

    names = {e.slug: e.name for e in db.query(InsuranceEntity).all()}
    rows = (db.query(InsuranceSeries)
            .filter(InsuranceSeries.entity_slug.isnot(None), InsuranceSeries.value.isnot(None))
            .all())
    latest: Dict[str, Dict[str, Any]] = {}
    seen_period: Dict[tuple, str] = {}
    for r in rows:
        d = latest.setdefault(r.entity_slug, {"slug": r.entity_slug,
                                              "name": names.get(r.entity_slug, r.entity_slug)})
        key = (r.entity_slug, r.series_code)
        if key not in seen_period or r.period > seen_period[key]:
            seen_period[key] = r.period
            d[r.series_code] = r.value
            d["period"] = max(d.get("period", ""), r.period)
    return list(latest.values())


def compute_isf(db: Session) -> List[Dict[str, Any]]:
    """Compute the ISF per insurer from ingested audited-statement series. Empty until
    the financials sync populates ``insurance_series`` per entity — never fabricated."""
    financials = _load_financials(db)
    return score_insurers(financials) if financials else []
