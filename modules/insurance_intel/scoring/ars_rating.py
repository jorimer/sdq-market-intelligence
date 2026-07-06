"""Índice de Solidez de ARS (ISARS) — health-risk-manager solidity index.

A 0-100 band index over the WELL-DEFINED regulatory metrics that SISALRIL publishes per
ARS (base BDFINAC), NOT a credit rating. Three dimensions (hybrid absolute band + peer
min-max, like the insurer ISF):

    margen_solvencia   0.50  inversiones que avalan / margen requerido  higher=better (≥1 = cumple)
    siniestralidad     0.30  gasto salud / ingreso salud (loss ratio)   lower ratio=better
    resultado          0.20  beneficio neto / ingreso salud             higher=better

Honesty directed by data: patrimonial solvency (patrimonio/activos) is a DECLARED GAP —
the BDFINAC trial-balance schema mixes stock/flow per plan and isn't fully documented, so
it's excluded rather than misread. ``coverage`` is over the declared 3-dimension model.
"""
import math
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

DIMENSIONS = [
    {"key": "margen_solvencia", "label": "Margen de solvencia (avala/requerido)", "weight": 0.50,
     "direction": "higher", "lo": 0.8, "hi": 3.0, "log": False},
    {"key": "siniestralidad", "label": "Siniestralidad médica (gasto/ingreso salud)", "weight": 0.30,
     "direction": "lower", "lo": 1.0, "hi": 0.6, "log": False},
    {"key": "resultado", "label": "Resultado técnico (beneficio/ingreso salud)", "weight": 0.20,
     "direction": "higher", "lo": -0.10, "hi": 0.15, "log": False},
]
_WABS = 0.5
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
        raw, lo, hi = math.log10(max(raw, 1.0)), math.log10(lo), math.log10(hi)
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
    g = fin.get
    if key == "margen_solvencia":
        req = g("ars.margen_requerido")
        return (g("ars.margen_inversiones") / req) if req else None
    if key == "siniestralidad":
        ing = g("ars.ingreso_salud")
        return (g("ars.gasto_salud") / ing) if ing else None
    if key == "resultado":
        ing = g("ars.ingreso_salud")
        return (g("ars.beneficio_neto") / ing) if ing else None
    return None


def score_ars(financials: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pure ISARS scorer over a list of ARS financials dicts (testable, no DB)."""
    raws = {f["slug"]: {d["key"]: _raw_metric(f, d["key"]) for d in DIMENSIONS} for f in financials}
    pools = {d["key"]: [raws[s][d["key"]] for s in raws if raws[s][d["key"]] is not None]
             for d in DIMENSIONS}
    total_weight = sum(d["weight"] for d in DIMENSIONS)
    out: List[Dict[str, Any]] = []
    for f in financials:
        slug = f["slug"]
        dims, num, wsum = [], 0.0, 0.0
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
        out.append({"slug": slug, "name": f.get("name", slug), "period": f.get("period"),
                    "category": f.get("category"),
                    "overall_score": overall, "band": band_for(overall) if coverage >= 0.99 else None,
                    "coverage": coverage, "dimensions": dims,
                    "score_kind": "absolute" if coverage >= 0.99 else "relative"})
    out.sort(key=lambda r: (r["overall_score"] is not None, r["overall_score"] or 0), reverse=True)
    return out


def _load_ars_financials(db: Session) -> List[Dict[str, Any]]:
    """Assemble each ARS's latest per-entity account figures from ``insurance_series``."""
    from modules.insurance_intel.models.models import InsuranceEntity, InsuranceSeries

    ents = {e.slug: e for e in db.query(InsuranceEntity)
            .filter(InsuranceEntity.entity_type == "ars").all()}
    if not ents:
        return []
    rows = (db.query(InsuranceSeries)
            .filter(InsuranceSeries.entity_slug.in_(list(ents)),
                    InsuranceSeries.series_code.like("ars.%"),
                    InsuranceSeries.value.isnot(None)).all())
    latest: Dict[str, Dict[str, Any]] = {}
    seen: Dict[tuple, str] = {}
    for r in rows:
        e = ents[r.entity_slug]
        d = latest.setdefault(r.entity_slug, {"slug": r.entity_slug, "name": e.name,
                                              "category": e.entity_code})
        key = (r.entity_slug, r.series_code)
        if key not in seen or r.period > seen[key]:
            seen[key] = r.period
            d[r.series_code] = r.value
            d["period"] = max(d.get("period", ""), r.period)
    return list(latest.values())


def compute_ars(db: Session) -> List[Dict[str, Any]]:
    """Compute the ISARS per ARS from ingested BDFINAC series. Empty until the ARS sync
    populates ``insurance_series`` — never fabricated."""
    fins = _load_ars_financials(db)
    return score_ars(fins) if fins else []
