"""SIS ingest → insurance market series + market snapshot (F1a).

Reads the SIS market data (premiums by ramo + active-insurer counts) — live from
CKAN ``datos.gob.do`` when reachable, else the committed real fixture — and upserts
it idempotently into ``insurance_series``, then computes a headline market snapshot.
Entity solvency (per-insurer ISF) lands in F1b via the audited-Excel + Power BI
channels; this sync is the market/Pulse spine.
"""
import logging
from datetime import date
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from shared.data.lineage import Lineage
from shared.data.sis_client import SISClient
from modules.insurance_intel.models.models import InsuranceSeries, InsuranceSnapshot

logger = logging.getLogger("sdq.insurance_intel.sis_sync")


def _frequency_for(period: str) -> str:
    if len(period) == 4 and period.isdigit():
        return "annual"
    if "-Q" in period:
        return "quarterly"
    return "monthly"


def _upsert_series(db: Session, records, *, lineage: Lineage) -> int:
    """Upsert market ``Record``s into ``insurance_series`` (own existence check —
    market rows have entity_slug NULL, keyed by (series_code, period, dimension))."""
    touched = 0
    for r in records:
        row = (
            db.query(InsuranceSeries)
            .filter(
                InsuranceSeries.series_code == r.series,
                InsuranceSeries.period == r.period,
                InsuranceSeries.entity_slug.is_(None),
                InsuranceSeries.dimension.is_(None)
                if r.dimension is None
                else InsuranceSeries.dimension == r.dimension,
            )
            .first()
        )
        if row is None:
            row = InsuranceSeries(
                series_code=r.series, period=r.period, entity_slug=None,
                dimension=r.dimension,
            )
            db.add(row)
        row.value = r.value
        row.unit = r.unit
        row.frequency = _frequency_for(r.period)
        row.source = lineage.source
        row.license = lineage.license
        row.published_at = lineage.published_at or lineage.fetched_at
        touched += 1
    return touched


def _compute_snapshot(db: Session) -> Optional[str]:
    """Capture the latest market total-premium + active-insurer count into a snapshot.

    Headline holds the most recent value of each market-level (non-dimensioned) series;
    the snapshot period is the newest month across them. Annual totals / growth / mix
    are derived on-read in ``service.build_market_pulse`` (kept flexible, not frozen)."""
    market = [
        s for s in db.query(InsuranceSeries)
        .filter(InsuranceSeries.entity_slug.is_(None), InsuranceSeries.dimension.is_(None))
        .all()
        if s.value is not None
    ]
    if not market:
        return None
    latest_by_code: Dict[str, InsuranceSeries] = {}
    for s in market:
        cur = latest_by_code.get(s.series_code)
        if cur is None or s.period > cur.period:
            latest_by_code[s.series_code] = s
    headline = {code: s.value for code, s in latest_by_code.items()}
    latest = max(s.period for s in latest_by_code.values())
    series_count = db.query(InsuranceSeries).count()

    snap = db.query(InsuranceSnapshot).filter(InsuranceSnapshot.period == latest).first()
    if snap is None:
        snap = InsuranceSnapshot(period=latest)
        db.add(snap)
    snap.headline = headline
    snap.series_count = float(series_count)
    snap.entity_count = 0.0  # insurers enumerated in F1b (audited financials)
    return latest


def sis_insurance_sync(
    db: Session,
    set_phase: Optional[Callable[[str], None]] = None,
    mode: str = "live",
) -> Dict:
    """Ingest SIS insurance-market data → series + market snapshot.

    ``mode='live'`` tries the CKAN download and falls back to the committed fixture
    on any failure (never aborts). ``mode='fixture'`` forces the committed sample.
    """
    set_phase = set_phase or (lambda _m: None)
    client = SISClient(mode="live" if mode == "live" else "fixture")
    client.check_license()
    lineage = Lineage(source=client.source, license=client.license, fetched_at=date.today())

    set_phase("Series de mercado (SIS · primas por ramo)")
    used_mode = client.mode
    try:
        records = client.fetch()
    except Exception as e:  # noqa: BLE001 — live network/parse failure → fixture floor
        logger.warning("[SIS] ingesta live falló (%s); uso fixture citado", e)
        client = SISClient(mode="fixture")
        records = client.fetch()
        used_mode = "fixture"

    market_rows = _upsert_series(db, records, lineage=lineage)

    set_phase("Snapshot del mercado")
    db.flush()
    snapshot_period = _compute_snapshot(db)

    db.commit()
    set_phase("Completado")
    return {
        "market_rows": market_rows,
        "snapshot_period": snapshot_period,
        "source": client.source,
        "mode": used_mode,
    }
