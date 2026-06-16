"""Macro-Political Risk — persistence + events service layer.

The scoring engine (`scoring/engine.py`) is deterministic and DB-agnostic.
This service runs it, persists the result as an :class:`IRMPSnapshot` (with its
per-dimension breakdown) and publishes ``irmp.updated`` so other axes
(banking_score outlook, sector_intel acceleration) can react — never by direct
table access.
"""
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.macro_political_risk.events import publish_irmp_updated
from modules.macro_political_risk.models.models import (
    Country,
    CountryVariable,
    DimensionScore,
    IRMPSnapshot,
    RiskBand,
)
from modules.macro_political_risk.scoring.engine import run_irmp

logger = logging.getLogger("sdq.macro_political_risk.service")


def _get_or_create_country(
    db: Session, iso_code: str, name: Optional[str] = None, region: Optional[str] = None
) -> Country:
    """Upsert a country by ISO code (peer-set registry)."""
    country = db.query(Country).filter_by(iso_code=iso_code).first()
    if country is None:
        country = Country(iso_code=iso_code, name=name or iso_code, region=region)
        db.add(country)
        db.flush()  # assign id without committing
    elif name and country.name == country.iso_code:
        # Backfill a real name if we only had the ISO placeholder.
        country.name = name
    return country


def compute_and_persist(
    db: Session,
    country_code: str,
    dataset: Dict[str, Dict[str, float]],
    period_end: date,
    country_name: Optional[str] = None,
    region: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute the IRMP for *country_code*, persist it and publish ``irmp.updated``.

    Idempotent per ``(country, period_end)``: re-running replaces the snapshot
    and its dimension rows in place.  Returns the engine result enriched with the
    persisted ``snapshot_id``.
    """
    result = run_irmp(country_code, dataset)  # raises KeyError if absent

    country = _get_or_create_country(db, country_code, country_name, region)

    snapshot = (
        db.query(IRMPSnapshot)
        .filter_by(country_id=country.id, period_end=period_end)
        .first()
    )
    if snapshot is None:
        snapshot = IRMPSnapshot(country_id=country.id, period_end=period_end)
        db.add(snapshot)

    snapshot.irmp_score = result["irmp_score"]
    snapshot.risk_band = RiskBand(result["risk_band"])  # value lookup ("Bajo" → bajo)
    snapshot.peer_set_size = result["peer_set_size"]
    snapshot.model_version = result["model_version"]
    snapshot.breakdown = result["dimensions"]

    # Replace per-dimension rows (delete-orphan cascade clears the old ones).
    snapshot.dimension_scores = [
        DimensionScore(
            dimension=dim,
            score=detail["score"],
            weight=detail["weight"],
            contribution=detail["contribution"],
        )
        for dim, detail in result["dimensions"].items()
    ]

    db.commit()
    db.refresh(snapshot)

    payload = {
        "country_code": country_code,
        "country_id": country.id,
        "snapshot_id": snapshot.id,
        "period_end": period_end.isoformat(),
        "irmp_score": result["irmp_score"],
        "risk_band": result["risk_band"],
    }
    publish_irmp_updated(payload)
    logger.info(
        "IRMP persistido y publicado: %s | %s → %s (%s)",
        country_code, period_end, result["irmp_score"], result["risk_band"],
    )

    return {**result, "snapshot_id": snapshot.id, "period_end": period_end.isoformat()}


def get_latest(db: Session, country_code: str) -> Optional[IRMPSnapshot]:
    """Most recent persisted snapshot for *country_code* (or None)."""
    return (
        db.query(IRMPSnapshot)
        .join(Country, Country.id == IRMPSnapshot.country_id)
        .filter(Country.iso_code == country_code)
        .order_by(IRMPSnapshot.period_end.desc())
        .first()
    )


def get_country_variables(
    db: Session, period: Optional[str] = None, source: Optional[str] = "WGI"
) -> Dict[str, Any]:
    """Read persisted variables grouped by country: ``{iso: {variable: value}}``.

    *source* filters to one upstream (e.g. ``"WGI"``); pass ``None`` to return
    every source (WGI + WDI + IMF_WEO + declared). When *period* is omitted, uses
    the most recent period present (annual → lexical sort over the 4-digit year).
    Returns the period actually used plus the variable list, so callers can
    overlay live data without fabricating missing values.
    """
    base = db.query(CountryVariable)
    if source is not None:
        base = base.filter(CountryVariable.source == source)

    if period is not None:
        rows = base.filter(CountryVariable.period == period).all()
    else:
        # Latest period PER (country, variable). Sources publish on different
        # lags (WGI vs WDI vs IMF), so a single global "max period" would silently
        # drop a source that trails — take each variable at its own latest instead.
        latest: Dict[tuple, CountryVariable] = {}
        for r in base.all():
            key = (r.iso_code, r.variable)
            cur = latest.get(key)
            if cur is None or r.period > cur.period:
                latest[key] = r
        rows = list(latest.values())

    countries: Dict[str, Dict[str, float]] = {}
    variables = set()
    used_periods = set()
    for r in rows:
        if r.value is None:  # missing stays missing — never overlaid downstream
            continue
        countries.setdefault(r.iso_code, {})[r.variable] = float(r.value)
        variables.add(r.variable)
        used_periods.add(r.period)
    return {
        "source": source or "ALL",
        # Representative period for display (the most recent observed). Individual
        # variables may be at an earlier period; values are each point-in-time.
        "period": (period or (max(used_periods) if used_periods else None)),
        "has_data": bool(countries),
        "countries": countries,
        "variables": sorted(variables),
    }


def get_history(db: Session, country_code: str, limit: int = 20) -> List[IRMPSnapshot]:
    """Snapshot history for *country_code*, most recent first."""
    return (
        db.query(IRMPSnapshot)
        .join(Country, Country.id == IRMPSnapshot.country_id)
        .filter(Country.iso_code == country_code)
        .order_by(IRMPSnapshot.period_end.desc())
        .limit(limit)
        .all()
    )
