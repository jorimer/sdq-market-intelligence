"""Pension Intel — system pulse (read side).

Builds the national pulse of the Dominican pension system from the ingested
series: the latest system headline (rentabilidad CCI/SDP, comisiones) plus the
per-AFP rentabilidad dispersion (leader, laggard, spread). Pure reads — no AI,
no mutation. The AI context (``ai_context.py``) digests this for the narrative.
"""
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.products.periods import period_sort_key
from modules.pension_intel.models.models import (
    PensionEntity,
    PensionSeries,
    PensionSnapshot,
)

# The per-AFP metric that drives the dispersion read.
_RENTABILIDAD = "rentabilidad_nominal_anual"


def _entity_names(db: Session) -> Dict[str, str]:
    return {e.slug: e.name for e in db.query(PensionEntity).all()}


def _latest_period(periods: List[str]) -> Optional[str]:
    # period_sort_key, no max() lexicográfico: los períodos mezclan formatos
    # ("2025" anual, "2025-04" mensual) y el año desnudo va después de sus meses.
    return max(periods, key=period_sort_key) if periods else None


def _afp_rentabilidad(db: Session, as_of: Optional[str] = None) -> Dict[str, Any]:
    """Latest per-AFP rentabilidad ranking + dispersion (leader/laggard/spread).

    ``as_of``: vista histórica — solo observaciones hasta ese período. El corte es
    cronológico (``period_sort_key``) en Python, no ``period <= as_of`` en SQL como
    en seguros, porque aquí los períodos mezclan formatos (mensual + anual)."""
    rows = (
        db.query(PensionSeries)
        .filter(
            PensionSeries.series_code == _RENTABILIDAD,
            PensionSeries.entity_slug.isnot(None),
            PensionSeries.value.isnot(None),
        )
        .all()
    )
    if as_of:
        cutoff = period_sort_key(as_of)
        rows = [r for r in rows if period_sort_key(str(r.period)) <= cutoff]
    period = _latest_period([r.period for r in rows])
    if period is None:
        return {"period": None, "ranking": [], "leader": None, "laggard": None, "spread": None}

    names = _entity_names(db)
    ranking = sorted(
        (
            {"slug": r.entity_slug, "name": names.get(r.entity_slug, r.entity_slug),
             "value": r.value, "unit": r.unit}
            for r in rows
            if r.period == period
        ),
        key=lambda d: d["value"],
        reverse=True,
    )
    leader = ranking[0] if ranking else None
    laggard = ranking[-1] if ranking else None
    spread = (
        round(leader["value"] - laggard["value"], 4)
        if leader and laggard and leader is not laggard
        else None
    )
    avg = round(sum(d["value"] for d in ranking) / len(ranking), 4) if ranking else None
    return {
        "period": period,
        "ranking": ranking,
        "leader": leader,
        "laggard": laggard,
        "spread": spread,
        "average": avg,
        "unit": "%",
    }


def _latest_snapshot(db: Session, as_of: Optional[str] = None) -> Optional[PensionSnapshot]:
    # Orden cronológico (period_sort_key) en Python: los períodos mezclan formatos
    # y el ``ORDER BY period DESC`` lexicográfico ordenaría mal el año desnudo.
    snaps = db.query(PensionSnapshot).all()
    if as_of:
        cutoff = period_sort_key(as_of)
        snaps = [s for s in snaps if period_sort_key(str(s.period)) <= cutoff]
    return max(snaps, key=lambda s: period_sort_key(str(s.period)), default=None)


def build_system_pulse(db: Session, as_of: Optional[str] = None) -> Dict[str, Any]:
    """The national pension pulse: system headline + per-AFP rentabilidad dispersion.

    ``as_of`` (un período del selector) produce la vista histórica: el headline sale
    del snapshot as-of (``sipen_sync._compute_snapshots`` materializa uno por período)
    y la dispersión por AFP se recalcula solo con observaciones hasta esa fecha. Sin
    ``as_of``, la vista más reciente (comportamiento original). Sin el pass-through,
    elegir un período histórico servía el pulso ACTUAL — mismo defecto corregido en
    seguros (PR #552)."""
    snap = _latest_snapshot(db, as_of=as_of)
    afp = _afp_rentabilidad(db, as_of=as_of)
    return {
        "period": as_of or (snap.period if snap else afp.get("period")),
        "headline": dict(snap.headline) if snap and snap.headline else {},
        "afp_rentabilidad": afp,
        "entity_count": int(snap.entity_count) if snap and snap.entity_count else db.query(PensionEntity).count(),
        "source": "SIPEN — sistema dominicano de pensiones",
        "model_version": snap.model_version if snap else "0.1",
    }
