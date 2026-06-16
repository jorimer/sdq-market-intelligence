"""Sector Intel — IAI + SGPS computation, persistence and events.

For a period it computes, per sector:
  * IAI via the shared index engine (sectors normalized against each other).
  * SGPS = Histórico/Estructural/Aceleración, where Aceleración reads the live
    upstream environment (macro/irmp/trade) from the acceleration context.

Persists SectorScore rows and publishes ``sector.updated``.
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.sector_intel.events import (
    acceleration_context,
    publish_sector_updated,
)
from modules.sector_intel.models.models import Sector, SectorScore
from modules.sector_intel.scoring.acceleration import compute_acceleration
from modules.sector_intel.scoring.iai import compute_iai
from modules.sector_intel.scoring.sgps import compute_sgps

logger = logging.getLogger("sdq.sector_intel.service")

MODEL_VERSION = "1.0"

# Sector catalog (decision 2026-06-16, owner): the full-economy leaf partition
# from the BCRD national accounts (~17 sectors summing to total Value Added),
# replacing the original 3 anchors. Single source of truth lives in
# ``shared.data.bcrd_sectors`` (the connector that populates them with real data).
from shared.data.bcrd_sectors import sector_catalog

ANCHOR_SECTORS = sector_catalog()


def seed_sectors(db: Session) -> int:
    """Ensure the sector catalog exists.  Returns how many were created."""
    created = 0
    for code, name in ANCHOR_SECTORS:
        if db.query(Sector).filter_by(code=code).first() is None:
            db.add(Sector(code=code, name=name))
            created += 1
    db.commit()
    return created


def compute_and_persist(
    db: Session,
    period: str,
    sector_dataset: Dict[str, Dict[str, float]],
    sgps_inputs: Optional[Dict[str, Dict[str, float]]] = None,
    country_code: str = "DO",
) -> Dict[str, Any]:
    """Compute IAI + SGPS for every sector in *sector_dataset*, persist, publish.

    Args:
        period: snapshot label.
        sector_dataset: ``{sector_code: {variable: value}}`` (IAI peer set).
        sgps_inputs: ``{sector_code: {"historical": x, "structural": y}}``.
        country_code: country whose IRMP feeds the acceleration factor.
    """
    if not sector_dataset:
        raise ValueError("Se requiere 'sector_dataset' con al menos un sector.")

    sgps_inputs = sgps_inputs or {}
    # The acceleration factor is the macro environment — shared across sectors.
    acceleration = compute_acceleration(acceleration_context, country_code)

    results: List[Dict[str, Any]] = []
    for sector_code in sector_dataset:
        iai = compute_iai(sector_code, sector_dataset)
        si = sgps_inputs.get(sector_code, {})
        sgps = compute_sgps(
            historical=si.get("historical"),
            structural=si.get("structural"),
            acceleration=acceleration["acceleration"],
        )

        row = (
            db.query(SectorScore)
            .filter_by(sector_code=sector_code, period=period)
            .first()
        )
        if row is None:
            row = SectorScore(sector_code=sector_code, period=period)
            db.add(row)
        row.iai_score = iai["iai_score"]
        row.iai_band = iai["band"]
        row.sgps_score = sgps["sgps_score"]
        row.iai_breakdown = iai["dimensions"]
        row.sgps_breakdown = {**sgps, "acceleration_detail": acceleration}
        row.model_version = MODEL_VERSION

        results.append({
            "sector_code": sector_code,
            "iai_score": iai["iai_score"],
            "iai_band": iai["band"],
            "sgps_score": sgps["sgps_score"],
        })

    db.commit()

    payload = {"period": period, "sectors": results, "acceleration": acceleration["acceleration"]}
    publish_sector_updated(payload)
    logger.info("Sector snapshot %s: %d sectores", period, len(results))
    return {
        "period": period,
        "country_code": country_code,
        "acceleration": acceleration,
        "sectors": results,
        "model_version": MODEL_VERSION,
    }


def get_sectors(db: Session) -> List[Sector]:
    return db.query(Sector).order_by(Sector.code).all()


def get_latest(db: Session, sector_code: str) -> Optional[SectorScore]:
    return (
        db.query(SectorScore)
        .filter_by(sector_code=sector_code)
        .order_by(SectorScore.period.desc())
        .first()
    )
