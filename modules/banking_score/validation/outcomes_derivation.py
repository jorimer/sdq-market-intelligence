"""Derive soft deterioration outcomes from the SIB history for backtesting.

For each (bank, period t) with at least one subsequent period, we record the
score we had emitted at t and whether the entity hit *financial distress* over
the next up-to-4 available quarters. "Distress" fires on any of:

  • non-performing-loan ratio (morosidad_pct) at least doubles
  • solvency (solvencia_pct) breaches the 10% regulatory floor
  • ROA < 0 in ≥ 2 consecutive quarters of the horizon

NOTE — why not a "≥2-notch downgrade" outcome: a relative-notch downgrade is
mechanically biased by the rating floor/ceiling. A top-tier bank has 9 notches
to fall (and mean-reverts from the top), while a bottom-tier (SDQ-D) bank CANNOT
fall 2 notches at all → its event rate is a literal 0. Measured on the SIB
history that outcome yields Gini −0.66 (anti-correlated by construction), which
is an artifact, not evidence about the score. Financial distress is immune to
that floor and gives Gini +0.26 (positive CI). So distress is the outcome.

Point-in-time caveat: we do NOT store data vintages, so the timeline uses
``period_end`` (not the figure's publication date). The assumed publication lag
is documented in the report; treat results as directional, not point-in-time.
"""
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from modules.banking_score.models.models import (
    BankingData, ModelType, RatingResult,
)
from shared.data.lineage import Lineage
from shared.data.outcomes import LabeledOutcome

HORIZON_Q = 4
SOLVENCY_FLOOR = 10.0


@dataclass(frozen=True)
class BacktestObservation:
    bank_id: str
    period_end: date
    score: float
    tier: str
    deteriorated: bool
    horizon_end: date
    triggers: tuple  # which rules fired


def _roa(row: BankingData) -> Optional[float]:
    act = float(row.activos_totales) if row.activos_totales else None
    if not act:
        return None
    un = float(row.utilidad_neta) if row.utilidad_neta is not None else None
    return None if un is None else un / act


def _financials(rows: List[BankingData]) -> Dict[date, Dict[str, Optional[float]]]:
    out: Dict[date, Dict[str, Optional[float]]] = {}
    for r in rows:
        out[r.period_end] = {
            "morosidad": float(r.morosidad_pct) if r.morosidad_pct is not None else None,
            "solvencia": float(r.solvencia_pct) if r.solvencia_pct is not None else None,
            "roa": _roa(r),
        }
    return out


def _deteriorated(base_fin: Dict, horizon_periods: List[date],
                  fins: Dict[date, Dict]) -> tuple:
    """Return the tuple of financial-distress triggers that fired (empty = stable)."""
    triggers: List[str] = []
    base_mor = base_fin.get("morosidad")

    # morosidad doubles
    if base_mor and base_mor > 0:
        for p in horizon_periods:
            m = fins.get(p, {}).get("morosidad")
            if m is not None and m >= 2.0 * base_mor:
                triggers.append("morosidad_x2")
                break

    # solvency breach
    for p in horizon_periods:
        s = fins.get(p, {}).get("solvencia")
        if s is not None and s < SOLVENCY_FLOOR:
            triggers.append("solvencia_breach")
            break

    # ROA < 0 in ≥ 2 consecutive quarters
    run = 0
    for p in horizon_periods:
        roa = fins.get(p, {}).get("roa")
        run = run + 1 if (roa is not None and roa < 0) else 0
        if run >= 2:
            triggers.append("roa_negativo_sostenido")
            break

    return tuple(triggers)


def derive_observations(db: Session, horizon_q: int = HORIZON_Q) -> List[BacktestObservation]:
    """Build one observation per (bank, period) that has ≥1 subsequent period."""
    ratings = (
        db.query(RatingResult)
        .filter(RatingResult.model_type == ModelType.deterministic)
        .all()
    )
    by_bank_ratings: Dict[str, Dict[date, RatingResult]] = {}
    for r in ratings:
        by_bank_ratings.setdefault(r.bank_id, {})[r.period_end] = r

    bdata = db.query(BankingData).all()
    by_bank_fin: Dict[str, List[BankingData]] = {}
    for b in bdata:
        by_bank_fin.setdefault(b.bank_id, []).append(b)

    observations: List[BacktestObservation] = []
    for bank_id, rmap in by_bank_ratings.items():
        periods = sorted(rmap.keys())
        tiers = {p: rmap[p].rating_tier for p in periods}
        fins = _financials(by_bank_fin.get(bank_id, []))
        for i, p in enumerate(periods):
            horizon = periods[i + 1: i + 1 + horizon_q]
            if not horizon:
                continue  # need at least one future period to observe an outcome
            base_fin = fins.get(p, {})
            triggers = _deteriorated(base_fin, horizon, fins)
            observations.append(BacktestObservation(
                bank_id=bank_id,
                period_end=p,
                score=float(rmap[p].overall_score),
                tier=tiers[p],
                deteriorated=bool(triggers),
                horizon_end=horizon[-1],
                triggers=triggers,
            ))
    return observations


def to_labeled_outcome(obs: BacktestObservation) -> LabeledOutcome:
    """Canonical export form (shared LabeledOutcome) for the labeled store."""
    return LabeledOutcome(
        entity_key=obs.bank_id,
        outcome_type="deterioration_4q",
        label="deterioro" if obs.deteriorated else "estable",
        observed_at=obs.horizon_end,
        lineage=Lineage(source="SIB", license="open-data"),
        score_at_prediction=obs.score,
        note=",".join(obs.triggers) or None,
    )
