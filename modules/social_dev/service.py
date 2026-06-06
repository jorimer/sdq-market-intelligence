"""Social Development — index computation, persistence and events."""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.social_dev.events import publish_social_updated
from modules.social_dev.models.models import DevelopmentScore
from modules.social_dev.scoring.development import (
    compute_development,
    distribution_stats,
)

logger = logging.getLogger("sdq.social_dev.service")

MODEL_VERSION = "1.0"


def compute_and_persist(
    db: Session, period: str, dataset: Dict[str, Dict[str, float]]
) -> Dict[str, Any]:
    """Compute the development index for every entity in *dataset*, persist, publish.

    *dataset* is ``{entity_key: {indicator: value}}`` (regions/groups as the peer
    set, so distribution — not just the mean — is reported).
    """
    if not dataset:
        raise ValueError("Se requiere 'dataset' con al menos una entidad.")

    results: List[Dict[str, Any]] = []
    for entity_key in dataset:
        dev = compute_development(entity_key, dataset)
        row = (
            db.query(DevelopmentScore)
            .filter_by(entity_key=entity_key, period=period)
            .first()
        )
        if row is None:
            row = DevelopmentScore(entity_key=entity_key, period=period)
            db.add(row)
        row.development_score = dev["development_score"]
        row.band = dev["band"]
        row.breakdown = dev["dimensions"]
        row.model_version = MODEL_VERSION
        results.append({
            "entity_key": entity_key,
            "development_score": dev["development_score"],
            "band": dev["band"],
        })

    db.commit()
    distribution = distribution_stats([r["development_score"] for r in results])

    payload = {"period": period, "entities": results, "distribution": distribution}
    publish_social_updated(payload)
    logger.info("Social snapshot %s: %d entidades", period, len(results))
    return {
        "period": period,
        "entities": results,
        "distribution": distribution,
        "model_version": MODEL_VERSION,
    }


def get_scores(db: Session, period: Optional[str] = None) -> List[DevelopmentScore]:
    q = db.query(DevelopmentScore)
    if period:
        q = q.filter_by(period=period)
    return q.order_by(DevelopmentScore.development_score.desc().nullslast()).all()


def get_latest(db: Session, entity_key: str) -> Optional[DevelopmentScore]:
    return (
        db.query(DevelopmentScore)
        .filter_by(entity_key=entity_key)
        .order_by(DevelopmentScore.period.desc())
        .first()
    )
