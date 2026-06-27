"""Persist the computed ISA per AFP into ``pension_ratings`` (idempotent upsert)."""
from typing import Dict

from sqlalchemy.orm import Session

from modules.pension_intel.models.models import PensionRating
from modules.pension_intel.scoring.isa import MODEL_VERSION, compute_isa


def score_and_persist(db: Session) -> Dict:
    """Recompute the ISA for every AFP and upsert one rating row per AFP/period.

    Returns a summary: how many ratings written and the as-of period(s).
    """
    results = compute_isa(db)
    written = 0
    for r in results:
        period = r["period"] or "n/d"
        row = (
            db.query(PensionRating)
            .filter(
                PensionRating.entity_slug == r["slug"],
                PensionRating.period == period,
            )
            .first()
        )
        if row is None:
            row = PensionRating(entity_slug=r["slug"], period=period)
            db.add(row)
        row.overall_score = r["overall_score"]
        row.band = r["band"]
        row.coverage = r["coverage"]
        row.dimensions = r["dimensions"]
        row.model_version = MODEL_VERSION
        written += 1
    return {"ratings_written": written, "afps": [r["slug"] for r in results]}
