"""Energy Intel — IRSE computation, persistence and events.

Reads the SIE open data (installed capacity + claims) via ``sie_client``, computes
the electric-sector resilience index (IRSE) for the latest year and persists it.
The energy transition dimension is a declared gap (no trustworthy CKAN source);
the index reports on capacity + service over real data only.
"""
import logging
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.energy_intel.events import publish_energy_updated
from modules.energy_intel.models.models import EnergyScore
from modules.energy_intel.scoring.resilience import compute_energy_index

logger = logging.getLogger("sdq.energy_intel.service")

MODEL_VERSION = "1.0"


def assemble_energy_dataset(
    capacity_by_year: Optional[Dict[int, float]] = None,
    claims: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Fetch SIE capacity + claims (live) unless provided, and compute the IRSE.

    Returns ``{period, index}`` where ``period`` is the latest capacity year. Raises
    if there is no capacity data (caller treats the sync as best-effort)."""
    if capacity_by_year is None or claims is None:
        from shared.data.sie_client import sie_client
        capacity_by_year = capacity_by_year or sie_client.installed_capacity()
        claims = claims if claims is not None else sie_client.claims()
    if not capacity_by_year:
        raise ValueError("SIE no devolvió capacidad instalada.")
    index = compute_energy_index(capacity_by_year, claims)
    period = str(max(capacity_by_year))
    return {"period": period, "index": index}


def compute_and_persist(
    db: Session,
    capacity_by_year: Optional[Dict[int, float]] = None,
    claims: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compute the IRSE for the latest year, persist it and publish ``energy.updated``.

    Idempotent per period: re-running replaces the score in place."""
    asm = assemble_energy_dataset(capacity_by_year, claims)
    period, index = asm["period"], asm["index"]

    row = db.query(EnergyScore).filter_by(period=period).first()
    if row is None:
        row = EnergyScore(period=period)
        db.add(row)
    row.energy_score = index["energy_score"]
    row.band = index["band"]
    row.coverage = index["coverage"]
    row.capacity_mw = (index["capacity"] or {}).get("capacity_mw")
    row.capacity_score = (index["capacity"] or {}).get("score")
    row.service_score = (index["service"] or {}).get("score")
    row.breakdown = {"dimensions": index["dimensions"], "capacity": index["capacity"],
                     "service": index["service"]}
    row.model_version = MODEL_VERSION

    db.commit()
    db.refresh(row)
    payload = {"period": period, "energy_score": index["energy_score"], "band": index["band"]}
    publish_energy_updated(payload)
    logger.info("IRSE %s: score=%s (%s), coverage=%s",
                period, index["energy_score"], index["band"], index["coverage"])
    return {"period": period, "score_id": row.id, **payload, "coverage": index["coverage"],
            "model_version": MODEL_VERSION}


def get_latest(db: Session, period: Optional[str] = None) -> Optional[EnergyScore]:
    q = db.query(EnergyScore)
    if period:
        return q.filter_by(period=period).first()
    return q.order_by(EnergyScore.period.desc()).first()


def get_scores(db: Session) -> List[EnergyScore]:
    return db.query(EnergyScore).order_by(EnergyScore.period.desc()).all()
