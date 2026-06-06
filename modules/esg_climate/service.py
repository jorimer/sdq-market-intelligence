"""ESG & Climate — exposure computation, persistence and events."""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.esg_climate.events import publish_esg_updated
from modules.esg_climate.models.models import ESGScore
from modules.esg_climate.scoring.exposure import compute_exposure

logger = logging.getLogger("sdq.esg_climate.service")

MODEL_VERSION = "1.0"


def compute_and_persist(
    db: Session, period: str, dataset: Dict[str, Dict[str, float]]
) -> Dict[str, Any]:
    """Compute ESG/climate exposure for each sector in *dataset*, persist, publish.

    *dataset* is ``{sector_key: {indicator: value}}`` (sectors as the peer set).
    """
    if not dataset:
        raise ValueError("Se requiere 'dataset' con al menos un sector.")

    results: List[Dict[str, Any]] = []
    for sector_key in dataset:
        exp = compute_exposure(sector_key, dataset)
        row = (
            db.query(ESGScore)
            .filter_by(sector_key=sector_key, period=period)
            .first()
        )
        if row is None:
            row = ESGScore(sector_key=sector_key, period=period)
            db.add(row)
        row.esg_score = exp["esg_score"]
        row.band = exp["band"]
        row.material = exp["materiality"]["material"]
        row.materiality_level = exp["materiality"]["level"]
        row.breakdown = {"dimensions": exp["dimensions"], "materiality": exp["materiality"]}
        row.model_version = MODEL_VERSION
        results.append({
            "sector_key": sector_key,
            "esg_score": exp["esg_score"],
            "band": exp["band"],
            "materiality": exp["materiality"]["level"],
        })

    db.commit()
    payload = {"period": period, "sectors": results}
    publish_esg_updated(payload)
    logger.info("ESG snapshot %s: %d sectores", period, len(results))
    return {"period": period, "sectors": results, "model_version": MODEL_VERSION}


def get_scores(db: Session, period: Optional[str] = None) -> List[ESGScore]:
    q = db.query(ESGScore)
    if period:
        q = q.filter_by(period=period)
    return q.order_by(ESGScore.esg_score.asc().nullslast()).all()  # most exposed first


def get_latest(db: Session, sector_key: str) -> Optional[ESGScore]:
    return (
        db.query(ESGScore)
        .filter_by(sector_key=sector_key)
        .order_by(ESGScore.period.desc())
        .first()
    )
