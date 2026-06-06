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
