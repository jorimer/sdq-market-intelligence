"""SIPEN ingest → pension series + system snapshot.

F0 reads the cited fixture sample (national + per-AFP) and upserts it idempotently
into ``pension_series``, seeds the AFP catalog, and computes a headline system
snapshot. Live channels (CKAN/XLSX/boletín/estados financieros) replace the
fixture path in later phases without touching this module's consumers.
"""
import logging
from datetime import date
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.data.lineage import Lineage
from shared.data.sipen_client import afp_catalog, fetch_sipen_ckan, sipen_client
from modules.pension_intel.models.models import (
    PensionEntity,
    PensionSeries,
    PensionSnapshot,
)

logger = logging.getLogger("sdq.pension_intel.sipen_sync")


def _frequency_for(period: str) -> str:
    """Infer cadence from the period label (Record drops the fixture's frequency)."""
    if len(period) == 4 and period.isdigit():
        return "annual"
    if "-Q" in period:
        return "quarterly"
    return "monthly"


def _seed_entities(db: Session) -> int:
    """Idempotently ensure each AFP exists in the catalog. Returns count created."""
    existing = {e.slug for e in db.query(PensionEntity).all()}
    created = 0
    names = sipen_client.entity_names()
    for slug, name in afp_catalog():
        if slug in existing:
            continue
        db.add(PensionEntity(slug=slug, name=names.get(slug, name), is_active=True))
        created += 1
    return created


def _upsert_series(
    db: Session, records, *, lineage: Lineage, entity_slug: Optional[str]
) -> int:
    """Upsert ``Record``\\ s into ``pension_series`` (own existence check — NULL
    entity_slug isn't deduped by the DB unique index). Returns rows touched."""
    touched = 0
    for r in records:
        row = (
            db.query(PensionSeries)
            .filter(
                PensionSeries.series_code == r.series,
                PensionSeries.period == r.period,
                PensionSeries.entity_slug.is_(None)
                if entity_slug is None
                else PensionSeries.entity_slug == entity_slug,
            )
            .first()
        )
        if row is None:
            row = PensionSeries(
                series_code=r.series, period=r.period, entity_slug=entity_slug,
            )
            db.add(row)
        row.value = r.value
        row.unit = r.unit
        row.frequency = _frequency_for(r.period)
        row.source = lineage.source
        row.license = lineage.license
        row.published_at = lineage.published_at
        touched += 1
    return touched


def _compute_snapshot(db: Session) -> Optional[str]:
    """Capture each system indicator's LATEST value into a snapshot row.

    Headline = the most recent value of every system series (not just those at one shared
    period), so a freshly-updated indicator (e.g. CKAN afiliados to 2026-05) doesn't drop
    a slower one (e.g. fixture rentabilidad at 2025-04) from the headline. The snapshot
    period is the newest period across them. None if there are no system series yet.
    """
    system = [
        s for s in db.query(PensionSeries).filter(PensionSeries.entity_slug.is_(None)).all()
        if s.value is not None
    ]
    if not system:
        return None
    latest_by_code: Dict[str, PensionSeries] = {}
    for s in system:
        cur = latest_by_code.get(s.series_code)
        if cur is None or s.period > cur.period:
            latest_by_code[s.series_code] = s
    headline = {code: s.value for code, s in latest_by_code.items()}
    latest = max(s.period for s in latest_by_code.values())
    entity_count = db.query(PensionEntity).count()
    series_count = db.query(PensionSeries).count()

    snap = db.query(PensionSnapshot).filter(PensionSnapshot.period == latest).first()
    if snap is None:
        snap = PensionSnapshot(period=latest)
        db.add(snap)
    snap.headline = headline
    snap.series_count = float(series_count)
    snap.entity_count = float(entity_count)
    return latest


def sipen_pension_sync(
    db: Session,
    set_phase: Optional[Callable[[str], None]] = None,
    only_latest: bool = False,
) -> Dict:
    """Ingest SIPEN pension data (system + per-AFP) → series + snapshot.

    Args:
        db: database session.
        set_phase: progress callback (UI), best-effort.
        only_latest: reserved for live mode (refresh only the latest period).

    Returns a summary: entities created, system/entity rows touched, snapshot period.
    """
    set_phase = set_phase or (lambda _m: None)
    sipen_client.check_license()

    set_phase("Catálogo de AFP")
    entities_created = _seed_entities(db)

    lineage = Lineage(
        source=sipen_client.source, license=sipen_client.license, fetched_at=date.today(),
    )

    set_phase("Series del sistema (SIPEN)")
    system_rows = _upsert_series(
        db, sipen_client.fetch(), lineage=lineage, entity_slug=None,
    )

    # Live national series from CKAN datos.gob.do (afiliados/cotizantes/salario, monthly
    # 2003-…) — moves the pulse off the fixture sample. Best-effort: a network failure
    # leaves the fixture floor intact and never aborts the sync.
    set_phase("Series live (CKAN datos.gob.do)")
    try:
        ckan = fetch_sipen_ckan(period=None)
    except Exception as e:  # noqa: BLE001
        logger.warning("[SIPEN] ingesta CKAN falló: %s", e)
        ckan = []
    if ckan:
        system_rows += _upsert_series(db, ckan, lineage=lineage, entity_slug=None)

    set_phase("Series por AFP")
    entity_records: List = sipen_client.fetch_entities()
    by_slug: Dict[str, list] = {}
    for r in entity_records:
        by_slug.setdefault(r.dimension, []).append(r)
    entity_rows = 0
    for slug, recs in by_slug.items():
        entity_rows += _upsert_series(db, recs, lineage=lineage, entity_slug=slug)

    set_phase("Snapshot del sistema")
    db.flush()  # make upserts visible to the snapshot/scoring queries (autoflush=False)
    snapshot_period = _compute_snapshot(db)

    set_phase("Índice de Solidez de AFP (ISA)")
    from modules.pension_intel.scoring.batch import score_and_persist
    ratings = score_and_persist(db)

    db.commit()
    set_phase("Completado")
    return {
        "entities_created": entities_created,
        "system_rows": system_rows,
        "ckan_rows": len(ckan),
        "entity_rows": entity_rows,
        "snapshot_period": snapshot_period,
        "ratings_written": ratings["ratings_written"],
        "source": sipen_client.source,
        "mode": sipen_client.mode,
    }
