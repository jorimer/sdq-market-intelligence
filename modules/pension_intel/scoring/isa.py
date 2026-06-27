"""Índice de Solidez de AFP (ISA) — explainable, declared-weight scoring.

Design (decision 2026-06-27, owner): score the AFPs on the REAL public SIPEN data
we have, with the SOLVENCY dimension as a DECLARED GAP (estados financieros pending,
channel D). This mirrors how the sector axis (IAI) mixes real + rúbrica declarada.

Two honesty devices, by design:
  * The AFP funds are NOT solvency-rated entities here (we lack their financials), so
    the output is a 0-100 index with BANDS (Sólida/Adecuada/En vigilancia/Frágil) —
    NOT the SDQ-AAA…D credit scale. This follows the fideicomiso precedent in
    banking_score (fund-like entities get their own band scale, not a credit rating).
  * Solvency carries the largest *declared* weight (0.35) but no data, so it is excluded
    from each AFP's score and the weight is renormalized over the present dimensions.
    The resulting ``coverage`` (≤ 0.65 until solvency lands) is surfaced verbatim — the
    number itself tells the reader the index is partial.

Dimensions are scored by peer min-max across the AFP panel (relative, like a percentile
floor/ceiling). Missing values stay absent — never imputed.
"""
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from modules.pension_intel.models.models import PensionEntity, PensionSeries

MODEL_VERSION = "0.1"

# Minimum real-data coverage to assign an overall band. Below this, an AFP is
# "datos insuficientes" (no band, no rank) rather than getting a solidity verdict
# from a single dimension — anti-overclaim, per the honest-gap doctrine. With
# solvency a declared gap (0.35), full public coverage tops out at 0.65; an AFP with
# only rentabilidad (0.30) falls below the gate and is shown unscored.
MIN_COVERAGE = 0.50

# ── Bands (0-100) — solidity index, NOT a credit rating ────────────────────────
BANDS: List[Tuple[str, float, float]] = [
    ("Sólida", 75.0, 100.0),
    ("Adecuada", 60.0, 75.0),
    ("En vigilancia", 45.0, 60.0),
    ("Frágil", 0.0, 45.0),
]


def band_for(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    for name, lo, hi in BANDS:
        if lo <= score <= hi:
            return name
    return "Frágil"


# ── Dimensions — declared full weights + provenance ────────────────────────────
# `metric` is the per-AFP PensionSeries.series_code; `ratio` dims are derived.
# `direction`: "higher" = more is better, "lower" = less is better.
DIMENSIONS: List[Dict[str, Any]] = [
    {
        "key": "solvencia", "label": "Solvencia", "weight": 0.35,
        "direction": "higher", "provenance": "brecha",
        "metric": None,  # GAP — estados financieros (canal D) pendientes
    },
    {
        "key": "rentabilidad", "label": "Rentabilidad", "weight": 0.30,
        "direction": "higher", "provenance": "real",
        "metric": "rentabilidad_nominal_anual",
    },
    {
        "key": "escala", "label": "Escala (patrimonio)", "weight": 0.20,
        "direction": "higher", "provenance": "real",
        "metric": "patrimonio_gestionado",
    },
    {
        "key": "costo", "label": "Costo (comisión/patrimonio)", "weight": 0.15,
        "direction": "lower", "provenance": "real",
        "ratio": ("comisiones_anual", "patrimonio_gestionado"),
    },
]
_TOTAL_WEIGHT = sum(d["weight"] for d in DIMENSIONS)


def _latest_value(db: Session, slug: str, metric: str) -> Optional[Tuple[str, float]]:
    """Latest (period, value) for a per-AFP metric, or None."""
    row = (
        db.query(PensionSeries)
        .filter(
            PensionSeries.entity_slug == slug,
            PensionSeries.series_code == metric,
            PensionSeries.value.isnot(None),
        )
        .order_by(PensionSeries.period.desc())
        .first()
    )
    return (row.period, row.value) if row else None


def _raw_values(db: Session, slugs: List[str]) -> Dict[str, Dict[str, Any]]:
    """Per-AFP raw inputs per dimension: {slug: {dim_key: (period, raw)}}.

    Ratio dims (costo) are computed from their two components' latest values.
    """
    out: Dict[str, Dict[str, Any]] = {s: {} for s in slugs}
    for slug in slugs:
        for d in DIMENSIONS:
            if d.get("metric"):
                v = _latest_value(db, slug, d["metric"])
                if v is not None:
                    out[slug][d["key"]] = v
            elif d.get("ratio"):
                num = _latest_value(db, slug, d["ratio"][0])
                den = _latest_value(db, slug, d["ratio"][1])
                if num is not None and den is not None and den[1]:
                    period = max(num[0], den[0])
                    out[slug][d["key"]] = (period, num[1] / den[1])
    return out


def _normalize(values: Dict[str, float], direction: str) -> Dict[str, float]:
    """Peer min-max → 0-100 (best=100). For 'lower' dims, invert. A single peer or
    a flat panel (min==max) maps everyone to a neutral 50 (no spurious spread)."""
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: 50.0 for k in values}
    out = {}
    for k, v in values.items():
        pct = (v - lo) / (hi - lo)  # 0..1, 1 = highest raw
        if direction == "lower":
            pct = 1.0 - pct
        out[k] = round(pct * 100.0, 2)
    return out


def compute_isa(db: Session) -> List[Dict[str, Any]]:
    """Compute the ISA for every active AFP. Returns one dict per AFP, sorted desc.

    Each result: slug, name, overall_score, band, coverage [0,1], period (as-of),
    and a per-dimension breakdown (raw, score, weight, provenance, present).
    """
    entities = db.query(PensionEntity).filter(PensionEntity.is_active.is_(True)).all()
    names = {e.slug: e.name for e in entities}
    slugs = list(names)
    if not slugs:
        return []

    raw = _raw_values(db, slugs)

    # Per-dimension peer normalization (only over AFPs that have the metric).
    dim_scores: Dict[str, Dict[str, float]] = {}
    for d in DIMENSIONS:
        present = {s: raw[s][d["key"]][1] for s in slugs if d["key"] in raw[s]}
        dim_scores[d["key"]] = _normalize(present, d["direction"]) if present else {}

    results: List[Dict[str, Any]] = []
    for slug in slugs:
        breakdown: List[Dict[str, Any]] = []
        weighted_sum = 0.0
        present_weight = 0.0
        periods: List[str] = []
        for d in DIMENSIONS:
            score = dim_scores[d["key"]].get(slug)
            present = score is not None
            raw_v = raw[slug].get(d["key"])
            if raw_v is not None:
                periods.append(raw_v[0])
            if present:
                weighted_sum += d["weight"] * score
                present_weight += d["weight"]
            breakdown.append({
                "key": d["key"], "label": d["label"], "weight": d["weight"],
                "direction": d["direction"], "provenance": d["provenance"],
                "present": present,
                "raw": round(raw_v[1], 4) if raw_v is not None else None,
                "score": score,
            })
        coverage = present_weight / _TOTAL_WEIGHT
        # Gate the verdict on minimum coverage: a single-dimension AFP is shown but
        # left unscored (no score/rank), never given a verdict it can't support.
        scoreable = present_weight > 0 and coverage >= MIN_COVERAGE
        overall = round(weighted_sum / present_weight, 2) if scoreable else None
        results.append({
            "slug": slug, "name": names[slug],
            # RELATIVE peer-position score (0-100), PARTIAL (solvency is a gap). Absolute
            # health BANDS (Sólida/Frágil) are DEFERRED until estados financieros land
            # (owner decision 2026-06-27): applying absolute bands to a relative score on
            # 3 AFPs would mislabel (e.g. brand a large AFP "Frágil" for placing last of 3).
            "overall_score": overall, "score_kind": "relative_partial",
            "band": None,  # deferred to F3 (band_for/BANDS kept for then)
            "coverage": round(coverage, 4),
            "scoreable": scoreable,
            "period": max(periods) if periods else None,
            "dimensions": breakdown,
        })

    results.sort(key=lambda r: (r["overall_score"] is not None, r["overall_score"] or 0), reverse=True)
    return results
