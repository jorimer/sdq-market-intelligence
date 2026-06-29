"""Tourism Intel — ITT computation, persistence and events.

Reads the ONE open data (non-resident air arrivals) via ``tourism_arrivals_client``,
computes the traction index (ITT) for the latest year and persists it.
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.tourism_intel.events import publish_tourism_updated
from modules.tourism_intel.models.models import TourismScore
from modules.tourism_intel.scoring.traction import compute_tourism_index

logger = logging.getLogger("sdq.tourism_intel.service")

MODEL_VERSION = "1.0"


def assemble_tourism_dataset(
    arrivals_by_year: Optional[Dict[int, Dict[str, object]]] = None,
) -> Dict[str, Any]:
    """Fetch arrivals (live) unless provided, and compute the ITT.

    Returns ``{period, index}`` where ``period`` is the latest year. Raises if there is
    no data (caller treats the sync as best-effort). Fully-provided inputs (tests) never
    hit the network."""
    if arrivals_by_year is None:
        from shared.data.tourism_arrivals_client import tourism_arrivals_client
        arrivals_by_year = tourism_arrivals_client.arrivals()
    if not arrivals_by_year:
        raise ValueError("ONE no devolvió llegadas de turismo.")
    index = compute_tourism_index(arrivals_by_year)
    period = str(max(arrivals_by_year))
    return {"period": period, "index": index}


def compute_and_persist(
    db: Session,
    arrivals_by_year: Optional[Dict[int, Dict[str, object]]] = None,
) -> Dict[str, Any]:
    """Compute the ITT for the latest year, persist it and publish ``tourism.updated``.

    Idempotent per period: re-running replaces the score in place."""
    asm = assemble_tourism_dataset(arrivals_by_year)
    period, index = asm["period"], asm["index"]

    row = db.query(TourismScore).filter_by(period=period).first()
    if row is None:
        row = TourismScore(period=period)
        db.add(row)
    levels = index["levels"] or {}
    row.itt_score = index["itt_score"]
    row.band = index["band"]
    row.coverage = index["coverage"]
    row.nonresident = levels.get("nonresident")
    row.foreign = levels.get("foreign")
    row.breakdown = {"dimensions": index["dimensions"], "total_demand": index["total_demand"],
                     "foreign_demand": index["foreign_demand"], "recovery": index["recovery"],
                     "diversification": index["diversification"], "levels": levels}
    row.model_version = MODEL_VERSION

    db.commit()
    db.refresh(row)
    payload = {"period": period, "itt_score": index["itt_score"], "band": index["band"]}
    publish_tourism_updated(payload)
    logger.info("ITT %s: score=%s (%s), coverage=%s",
                period, index["itt_score"], index["band"], index["coverage"])
    return {"period": period, "score_id": row.id, **payload, "coverage": index["coverage"],
            "model_version": MODEL_VERSION}


def get_latest(db: Session, period: Optional[str] = None) -> Optional[TourismScore]:
    q = db.query(TourismScore)
    if period:
        return q.filter_by(period=period).first()
    return q.order_by(TourismScore.period.desc()).first()


def get_scores(db: Session) -> List[TourismScore]:
    return db.query(TourismScore).order_by(TourismScore.period.desc()).all()
