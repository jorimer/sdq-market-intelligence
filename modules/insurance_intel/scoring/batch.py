"""Persist ISF ratings — recompute every insurer and upsert one row per entity/period."""
import logging
from typing import Dict

from sqlalchemy.orm import Session

from modules.insurance_intel.models.models import InsuranceRating
from modules.insurance_intel.scoring.isf import compute_isf

logger = logging.getLogger("sdq.insurance_intel.batch")

# 0.2 — el resultado técnico pasa a ser el margen técnico (1 − combined ratio), corrigiendo
# el doble conteo de siniestros de la 0.1. Todo score recalculado queda marcado con esta
# versión: un cambio de banda entre 0.1 y 0.2 es metodológico, NO deterioro de la entidad.
MODEL_VERSION = "0.2"


def score_and_persist(db: Session) -> Dict:
    """Recompute the ISF and upsert one rating row per insurer/period. Idempotent."""
    results = compute_isf(db)
    written = 0
    for r in results:
        row = (db.query(InsuranceRating)
               .filter(InsuranceRating.entity_slug == r["slug"],
                       InsuranceRating.period == (r["period"] or "—")).first())
        if row is None:
            row = InsuranceRating(entity_slug=r["slug"], period=r["period"] or "—")
            db.add(row)
        row.overall_score = r["overall_score"]
        row.band = r["band"]
        row.coverage = r["coverage"]
        row.dimensions = r["dimensions"]
        row.model_version = MODEL_VERSION
        written += 1
    db.flush()
    return {"ratings_written": written, "insurers": [r["slug"] for r in results]}
