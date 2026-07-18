"""SIPEN ingest → pension series + system snapshot.

F0 reads the cited fixture sample (national + per-AFP) and upserts it idempotently
into ``pension_series``, seeds the AFP catalog, and computes a headline system
snapshot. Live channels (CKAN/XLSX/boletín/estados financieros) replace the
fixture path in later phases without touching this module's consumers.
"""
import logging
from bisect import bisect_right
from datetime import date
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.data.lineage import Lineage
from shared.products.periods import period_sort_key
from shared.data.sipen_client import (
    afp_catalog,
    fetch_sipen_ckan,
    fetch_sipen_rentabilidad,
    sipen_client,
)
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
        # Stamp a real refresh date (the source rarely dates each point) so the product
        # readiness G1 has a freshness signal — consistent with financials/cartera syncs.
        row.published_at = lineage.published_at or lineage.fetched_at
        touched += 1
    return touched


def _compute_snapshots(db: Session) -> Optional[str]:
    """Materialize one system snapshot POR PERÍODO histórico (backfill idempotente).

    Antes solo se materializaba el período más reciente de cada corrida → el selector
    de períodos del producto ofrecía únicamente los períodos que fueron "el último"
    en algún sync (2 opciones en prod), pese a que las series SIPEN traen historia
    mensual desde 2003-07 — mismo defecto corregido en seguros (PR #552). Ahora cada
    período con dato del sistema tiene su snapshot: el headline guarda el valor as-of
    (el más reciente de cada indicador a esa fecha), misma semántica que tenía el
    snapshot "latest" (un indicador fresco no descarta a uno más lento). A diferencia
    de seguros, los períodos mezclan formatos ("2025-04" mensual, "2025" anual) →
    el orden cronológico es ``period_sort_key`` (el año desnudo va DESPUÉS de sus
    meses: la cifra anual se conoce al cierre del año), no el lexicográfico.
    Devuelve el período más reciente; None si no hay series del sistema."""
    system = [
        s for s in db.query(PensionSeries).filter(PensionSeries.entity_slug.is_(None)).all()
        if s.value is not None
    ]
    if not system:
        return None
    # str(): a nivel de instancia ya es str; el cast es para mypy (modelo estilo Column).
    existing: Dict[str, PensionSnapshot] = {
        str(s.period): s for s in db.query(PensionSnapshot).all()}
    by_period: Dict[str, List[PensionSeries]] = {}
    for s in system:
        by_period.setdefault(str(s.period), []).append(s)
    periods = sorted(by_period, key=period_sort_key)
    entity_count = float(db.query(PensionEntity).count())
    # series_count as-of por bisect (una sola query, no un COUNT por período).
    all_period_keys = sorted(
        period_sort_key(str(p)) for (p,) in db.query(PensionSeries.period).all())
    latest_by_code: Dict[str, PensionSeries] = {}
    for period in periods:  # ascendente cronológico: latest_by_code acumula el as-of
        for s in by_period[period]:
            latest_by_code[s.series_code] = s
        snap = existing.get(period)
        if snap is None:
            snap = PensionSnapshot(period=period)
            db.add(snap)
            existing[period] = snap
        snap.headline = {code: s.value for code, s in latest_by_code.items()}
        snap.series_count = float(bisect_right(all_period_keys, period_sort_key(period)))
        snap.entity_count = entity_count
    return periods[-1]


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

    # Live rentabilidad (system CCI/Sistema + per-AFP) from the Estadística Previsional
    # XLSX — moves the return series off the fixture sample onto the full monthly history
    # (2003-…). Best-effort: a network/parse failure leaves the fixture floor intact.
    set_phase("Rentabilidad live (XLSX Estadística Previsional)")
    try:
        rent_sys, rent_ent = fetch_sipen_rentabilidad(period=None)
    except Exception as e:  # noqa: BLE001
        logger.warning("[SIPEN] ingesta rentabilidad XLSX falló: %s", e)
        rent_sys, rent_ent = [], []
    rentabilidad_rows = 0
    if rent_sys:
        rentabilidad_rows += _upsert_series(db, rent_sys, lineage=lineage, entity_slug=None)
    if rent_ent:
        rent_by_slug: Dict[str, list] = {}
        for r in rent_ent:
            rent_by_slug.setdefault(r.dimension, []).append(r)
        for slug, recs in rent_by_slug.items():
            rentabilidad_rows += _upsert_series(db, recs, lineage=lineage, entity_slug=slug)

    set_phase("Snapshot del sistema (backfill por período)")
    db.flush()  # make upserts visible to the snapshot/scoring queries (autoflush=False)
    snapshot_period = _compute_snapshots(db)

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
        "rentabilidad_rows": rentabilidad_rows,
        "snapshot_period": snapshot_period,
        "ratings_written": ratings["ratings_written"],
        "source": sipen_client.source,
        "mode": sipen_client.mode,
    }
