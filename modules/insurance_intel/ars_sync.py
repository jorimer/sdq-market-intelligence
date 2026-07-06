"""SISALRIL BDFINAC ingest → per-ARS financial series + ISARS ratings.

Ingests the ARS (health-risk-manager) regulatory financial figures — margen de solvencia,
ingreso/gasto en salud, beneficio neto — live from the SISALRIL download endpoint when
reachable, else the committed fixture, into ``insurance_series`` (entity_type ``ars``),
seeds the ARS roster, and computes the ISARS (Índice de Solidez de ARS). Idempotent.
"""
import logging
from datetime import date
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from shared.data.lineage import Lineage
from shared.data.sisalril_ars_client import (
    SISALRILARSClient,
    ars_categories,
    ars_name,
)
from modules.insurance_intel.models.models import (
    InsuranceEntity,
    InsuranceRating,
    InsuranceSeries,
)

logger = logging.getLogger("sdq.insurance_intel.ars_sync")


def _seed_entities(db: Session, ars_ids, cats: Dict[str, int]) -> int:
    """Seed/refresh ARS entities with their OFFICIAL names (SISALRIL Portal Estadístico).
    Also upgrades names already seeded as coded 'ARS 001 (...)' placeholders."""
    existing = {e.slug: e for e in db.query(InsuranceEntity)
                .filter(InsuranceEntity.entity_type == "ars").all()}
    created = 0
    for ars_id in ars_ids:
        slug = f"ars_{ars_id}"
        cat = cats.get(ars_id)
        name = ars_name(ars_id, cat)
        ent = existing.get(slug)
        if ent is None:
            db.add(InsuranceEntity(slug=slug, name=name, entity_type="ars",
                                   entity_code=str(cat) if cat else None, is_active=True))
            created += 1
        else:
            ent.name = name  # upgrade to the official name
            if cat and not ent.entity_code:
                ent.entity_code = str(cat)
    return created


def _upsert_series(db: Session, records, *, lineage: Lineage) -> int:
    touched = 0
    for r in records:
        slug = f"ars_{r.dimension}"
        row = (db.query(InsuranceSeries)
               .filter(InsuranceSeries.series_code == r.series,
                       InsuranceSeries.period == r.period,
                       InsuranceSeries.entity_slug == slug,
                       InsuranceSeries.dimension.is_(None)).first())
        if row is None:
            row = InsuranceSeries(series_code=r.series, period=r.period, entity_slug=slug)
            db.add(row)
        row.value = r.value
        row.unit = r.unit
        row.frequency = "monthly"
        row.source = lineage.source
        row.license = lineage.license
        row.published_at = lineage.fetched_at
        touched += 1
    return touched


def _persist_ratings(db: Session) -> int:
    from modules.insurance_intel.scoring.ars_rating import compute_ars
    written = 0
    for r in compute_ars(db):
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
        row.model_version = "ars-0.1"
        written += 1
    return written


def ars_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None,
             mode: str = "live") -> Dict:
    """Ingest ARS financial series (BDFINAC) → roster + series + ISARS ratings."""
    set_phase = set_phase or (lambda _m: None)
    client = SISALRILARSClient(mode="live" if mode == "live" else "fixture")
    client.check_license()
    lineage = Lineage(source=client.source, license=client.license, fetched_at=date.today())

    set_phase("Estados financieros de ARS (SISALRIL · BDFINAC)")
    used = client.mode
    try:
        records = client.fetch()
    except Exception as e:  # noqa: BLE001 — live failure → committed fixture floor
        logger.warning("[SISALRIL-ARS] ingesta live falló (%s); uso fixture citado", e)
        client = SISALRILARSClient(mode="fixture")
        records = client.fetch()
        used = "fixture"

    ars_ids = sorted({r.dimension for r in records if r.dimension})
    set_phase("Roster de ARS")
    created = _seed_entities(db, ars_ids, ars_categories())
    set_phase("Series por ARS")
    rows = _upsert_series(db, records, lineage=lineage)
    db.flush()

    set_phase("Índice de Solidez de ARS (ISARS)")
    ratings = _persist_ratings(db)
    db.commit()
    set_phase("Completado")
    return {"ars": len(ars_ids), "entities_created": created, "series_rows": rows,
            "ratings_written": ratings, "source": client.source, "mode": used}
