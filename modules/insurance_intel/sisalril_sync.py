"""SISALRIL/CNSS ingest → SFS health-coverage series.

Ingests the national Family Health Insurance (SFS) affiliation series (total +
contributory/subsidized regimes) — live from the CNSS CSV when reachable, else the
committed fixture — into ``insurance_series`` (source ``SISALRIL``). These power the
health-coverage face of SDQ Seguros (the SISALRIL sub-sector). The ARS entity rating
is a separate deferred track (financials behind the REDATAM Dash portal).
"""
import logging
from datetime import date
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from shared.data.lineage import Lineage
from shared.data.sisalril_client import SISALRILClient
from modules.insurance_intel.models.models import InsuranceSeries

logger = logging.getLogger("sdq.insurance_intel.sisalril_sync")


def _upsert(db: Session, records, *, lineage: Lineage) -> int:
    touched = 0
    for r in records:
        row = (db.query(InsuranceSeries)
               .filter(InsuranceSeries.series_code == r.series,
                       InsuranceSeries.period == r.period,
                       InsuranceSeries.entity_slug.is_(None),
                       InsuranceSeries.dimension.is_(None) if r.dimension is None
                       else InsuranceSeries.dimension == r.dimension).first())
        if row is None:
            row = InsuranceSeries(series_code=r.series, period=r.period, entity_slug=None,
                                  dimension=r.dimension)
            db.add(row)
        row.value = r.value
        row.unit = r.unit
        row.frequency = "monthly"
        row.source = lineage.source
        row.license = lineage.license
        row.published_at = lineage.fetched_at
        touched += 1
    return touched


def sisalril_sfs_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None,
                      mode: str = "live") -> Dict:
    """Ingest the SFS health-coverage series (total + regimes) → insurance_series."""
    set_phase = set_phase or (lambda _m: None)
    client = SISALRILClient(mode="live" if mode == "live" else "fixture")
    client.check_license()
    lineage = Lineage(source=client.source, license=client.license, fetched_at=date.today())

    set_phase("Cobertura SFS (SISALRIL/CNSS)")
    used = client.mode
    try:
        records = client.fetch()
    except Exception as e:  # noqa: BLE001 — live failure → committed fixture floor
        logger.warning("[SISALRIL] ingesta live falló (%s); uso fixture citado", e)
        client = SISALRILClient(mode="fixture")
        records = client.fetch()
        used = "fixture"

    rows = _upsert(db, records, lineage=lineage)
    db.commit()
    set_phase("Completado")
    return {"sfs_rows": rows, "source": client.source, "mode": used}
