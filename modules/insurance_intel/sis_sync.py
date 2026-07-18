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


def _compute_snapshots(db: Session) -> Optional[str]:
    """Materialize one market snapshot POR PERÍODO histórico (backfill idempotente).

    Antes solo se materializaba el período más reciente de cada corrida → el selector
    de períodos del producto ofrecía únicamente los períodos que fueron "el último"
    en algún sync (2 opciones en prod), pese a que las series traen historia desde
    2020-11 — bug real detectado en producción. Ahora cada período con dato de mercado
    tiene su snapshot: el headline guarda el valor as-of (el más reciente de cada
    serie de mercado a esa fecha), misma semántica que tenía el snapshot "latest".
    Los agregados anuales/mix se siguen derivando on-read en
    ``service.build_market_pulse`` (flexible, no congelado). Devuelve el más reciente."""
    market = [
        s for s in db.query(InsuranceSeries)
        .filter(InsuranceSeries.entity_slug.is_(None), InsuranceSeries.dimension.is_(None))
        .all()
        if s.value is not None
    ]
    if not market:
        return None
    # str(): a nivel de instancia ya es str; el cast es para mypy (modelo estilo Column).
    existing: Dict[str, InsuranceSnapshot] = {
        str(s.period): s for s in db.query(InsuranceSnapshot).all()}
    periods = sorted({str(s.period) for s in market})
    latest_by_code: Dict[str, InsuranceSeries] = {}
    for period in periods:  # ascendente: latest_by_code acumula el as-of de cada período
        for s in market:
            if s.period == period:
                cur = latest_by_code.get(s.series_code)
                if cur is None or s.period > cur.period:
                    latest_by_code[s.series_code] = s
        headline = {code: s.value for code, s in latest_by_code.items()}
        series_count = db.query(InsuranceSeries).filter(
            InsuranceSeries.period <= period).count()
        snap = existing.get(period)
        if snap is None:
            snap = InsuranceSnapshot(period=period)
            db.add(snap)
            existing[period] = snap
        snap.headline = headline
        snap.series_count = float(series_count)
        snap.entity_count = 0.0  # insurers enumerated in F1b (audited financials)
    return periods[-1]


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

    set_phase("Snapshot del mercado (backfill por período)")
    db.flush()
    snapshot_period = _compute_snapshots(db)

    db.commit()
    set_phase("Completado")
    return {
        "market_rows": market_rows,
        "snapshot_period": snapshot_period,
        "source": client.source,
        "mode": used_mode,
    }
