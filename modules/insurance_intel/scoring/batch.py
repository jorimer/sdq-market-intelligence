"""Persist ISF ratings — recompute every insurer and upsert one row per entity/period."""
import logging
from typing import Dict

from sqlalchemy.orm import Session

from modules.insurance_intel.models.models import InsuranceRating
from modules.insurance_intel.scoring.isf import compute_isf

logger = logging.getLogger("sdq.insurance_intel.batch")

# Versión de metodología. Todo score recalculado queda marcado con la suya: un cambio de
# banda ENTRE versiones es metodológico, NO deterioro de la entidad. Sin esto, una
# recalibración se leería en el histórico como si la aseguradora hubiera empeorado.
#   0.2 — el resultado técnico pasa a ser el margen técnico (1 − combined ratio),
#         corrigiendo el doble conteo de siniestros de la 0.1.
#   0.3 — recalibración: peer min-max con límites robustos, `escala` medida en espacio log
#         también en el min-max, y bandas absolutas de dos tramos ancladas en el umbral
#         regulatorio / breakeven (docs/PROPUESTA_ANCLAJES_ISF.md).
#   0.4 — techo de banda por incumplimiento del margen de SOLVENCIA (Ley 146-02): quien está
#         bajo el mínimo de capital no puede superar "En vigilancia". No altera el score,
#         solo la etiqueta cualitativa. Decisión de producto del dueño.
MODEL_VERSION = "0.4"


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
