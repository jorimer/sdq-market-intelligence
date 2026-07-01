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

Dimensions with a declared anchor (rentabilidad, escala, solvencia) are scored by a
HYBRID: half an ABSOLUTE band (fixed anchors → magnitude, outlier-immune) + half peer
min-max (relative discrimination). Pure min-max sent the tight-pack edges to 0/100 and
let one outlier re-anchor the panel; the hybrid communicates magnitude while keeping the
relative signal (Fase 6, ``_ANCHORS``/``_score_hybrid``). COSTO keeps its own absolute
%-band. Missing values stay absent — never imputed.
"""
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from modules.pension_intel.models.models import PensionEntity, PensionSeries

MODEL_VERSION = "0.2"  # Fase 6: híbrido banda-absoluta + min-max (antes: min-max puro)

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
        "key": "solvencia", "label": "Solvencia (patrimonio/activos)", "weight": 0.35,
        "direction": "higher", "provenance": "real",
        # Real once the AFP's estados financieros are ingested (financials_sync →
        # patrimonio + activos_totales series). Absent (present=False) until then — the
        # AFP stays relative/partial; with it, the ISA emits its ABSOLUTE band.
        "ratio": ("patrimonio", "activos_totales"),
    },
    {
        "key": "rentabilidad", "label": "Rentabilidad", "weight": 0.30,
        "direction": "higher", "provenance": "real",
        "metric": "rentabilidad_nominal_anual",
    },
    {
        "key": "escala", "label": "Escala (fondos administrados / AUM)", "weight": 0.20,
        "direction": "higher", "provenance": "real",
        # AUM from each AFP's own estados financieros ('Activos de los Fondos Administrados'),
        # so all AFPs share one consistent source → present once financials are ingested.
        "metric": "fondos_administrados",
    },
    {
        "key": "costo", "label": "Costo (comisión/AUM)", "weight": 0.15,
        "direction": "lower", "provenance": "real",
        "ratio": ("comisiones_anual", "fondos_administrados"),
    },
]
_TOTAL_WEIGHT = sum(d["weight"] for d in DIMENSIONS)


def _latest_value(db: Session, slug: str, metric: str):
    """Latest (period, value, unit) for a per-AFP metric, or None."""
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
    return (row.period, row.value, row.unit) if row else None


def _to_rd(value: float, unit: Optional[str]) -> float:
    """Normalize a monetary value to RD$ base units. Some SIPEN series arrive in
    millions ('RD$ MM'); dividing a millions numerator by an RD$ denominator (as the
    costo ratio did) silently yields a ~0 raw that displays as 'comisión = 0.0'. Scale
    by the declared unit so ratios are unit-consistent regardless of source."""
    u = (unit or "").lower()
    if "mm" in u or "millon" in u:
        return value * 1_000_000.0
    return value


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
                    # unit-normalize both operands (RD$ MM vs RD$) before dividing.
                    ratio = _to_rd(num[1], num[2]) / _to_rd(den[1], den[2])
                    if d["key"] == "costo":
                        ratio *= 100.0  # comisión/AUM as a % (readable, ~0.6-0.9%)
                    out[slug][d["key"]] = (period, ratio)
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


# Costo (comisión/AUM, %) is scored on an ABSOLUTE band, not peer min-max. DR AFP
# commissions cluster in a narrow ~0.6-0.9% range, so min-max amplified a ~0.2pp real
# spread into the full 0-100 score — the marginally-cheapest AFP looked "structurally"
# cheapest. The band reflects real economics: cheap ≤0.4% → 100, expensive ≥1.2% → 0.
_COSTO_GOOD_PCT = 0.4
_COSTO_BAD_PCT = 1.2


def _score_costo_absolute(pct: float) -> float:
    span = _COSTO_BAD_PCT - _COSTO_GOOD_PCT
    return round(max(0.0, min(100.0, (_COSTO_BAD_PCT - pct) / span * 100.0)), 2)


# ── Hardening del min-max (Fase 6, decisión dueño 2026-07-01) ──────────────────
# El min-max PURO produce artefactos: un pack apretado (rentabilidad ~6-9%) manda al
# borde inferior a 0 y al superior a 100, y un outlier re-ancla todo el panel; el score
# no comunica MAGNITUD, solo rango. Se reemplaza por un HÍBRIDO: mezcla una banda ABSOLUTA
# (anclas fijas → magnitud, inmune a outliers) con el peer min-max (discriminación
# relativa). ``score = WABS·absoluta + (1-WABS)·minmax``. costo mantiene su banda propia.
# Anclas (raw→0..100) calibradas a la distribución real de las 7 AFP + sentido económico.
_HYBRID_WABS = 0.5
# (lo→0, hi→100, log): rentabilidad nominal %, solvencia patrimonio/activos, escala AUM RD$.
_ANCHORS: Dict[str, Tuple[float, float, bool]] = {
    "rentabilidad": (5.0, 12.0, False),   # 5% ≈ apenas sobre inflación; 12% fuerte
    "solvencia": (0.5, 1.0, False),       # 0.5 débil; 1.0 muy sólido
    "escala": (10e9, 500e9, True),        # 10bn→0, 500bn→100 en escala log (AUM ~2 órdenes)
}


def _absolute_band(v: float, lo: float, hi: float, log: bool) -> float:
    """Banda absoluta lineal raw→0..100 (higher = mejor), con clamp. *log*: escala log10
    (para AUM, que abarca dos órdenes de magnitud)."""
    import math
    if log:
        v, lo, hi = math.log10(max(v, 1.0)), math.log10(lo), math.log10(hi)
    return max(0.0, min(100.0, (v - lo) / (hi - lo) * 100.0))


def _score_hybrid(present: Dict[str, float], key: str, direction: str) -> Dict[str, float]:
    """Híbrido banda-absoluta + peer min-max para una dimensión con anclas. Preserva la
    discriminación relativa del panel y ancla la magnitud (un outlier no re-ancla)."""
    lo, hi, log = _ANCHORS[key]
    mm = _normalize(present, direction)
    return {s: round(_HYBRID_WABS * _absolute_band(v, lo, hi, log)
                     + (1.0 - _HYBRID_WABS) * mm[s], 2)
            for s, v in present.items()}


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
        if d["key"] == "costo":
            # Absolute band (not peer min-max) — see _score_costo_absolute.
            dim_scores[d["key"]] = {s: _score_costo_absolute(v) for s, v in present.items()}
        elif d["key"] in _ANCHORS and present:
            # Híbrido banda-absoluta + min-max (Fase 6): magnitud + discriminación relativa.
            dim_scores[d["key"]] = _score_hybrid(present, d["key"], d["direction"])
        else:
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
        # ABSOLUTE band emits ONLY when solvency (estados financieros) is present: until
        # then the score is a RELATIVE peer position and an absolute "Sólida/Frágil"
        # verdict would overclaim (owner decision 2026-06-27). Once an AFP's financials
        # land, its solvency dimension turns present → it graduates to an absolute band.
        solvency_present = any(d["key"] == "solvencia" and d["present"] for d in breakdown)
        emit_band = scoreable and solvency_present
        results.append({
            "slug": slug, "name": names[slug],
            "overall_score": overall,
            "score_kind": "absolute" if emit_band else "relative_partial",
            "band": band_for(overall) if emit_band else None,
            "coverage": round(coverage, 4),
            "scoreable": scoreable,
            "period": max(periods) if periods else None,
            "dimensions": breakdown,
        })

    results.sort(key=lambda r: (r["overall_score"] is not None, r["overall_score"] or 0), reverse=True)
    return results
