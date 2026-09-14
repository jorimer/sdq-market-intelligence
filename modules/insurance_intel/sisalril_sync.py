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
# A nivel de módulo y no dentro de la función: `Base.metadata` tiene que conocer la tabla
# al arrancar, o no existe cuando la base se monta desde el metadata (tests, informes a
# mano). Lo vigila `shared/tests/test_alembic_ve_todas_las_tablas.py`.
from shared.observations.models import SectorObservation  # noqa: F401

#: Clave del eje en la tabla transversal de observaciones.
SECTOR_KEY_OBS = "insurance"

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


def escribir_observaciones_sfs(db: Session, records, *, source: str, license: str) -> int:
    """Las series SFS en `sector_observations`, para el feed mensual. No commitea.

    Conviven con `insurance_series` (plan §2.1: no se migra): el mismo lote se escribe en las
    dos, y un test cuenta que por período coincidan. Idempotente como el MIVHED: el CSV del CNSS
    es el archivo COMPLETO en cada descarga, así que se borra la serie y se reescribe; un
    upsert fila a fila dejaría vivos los meses que el emisor haya retirado.

    `published_at` queda en NULL a propósito. El conector solo sabe cuándo DESCARGÓ el archivo,
    no cuándo lo publicó el CNSS: poner la fecha de descarga ahí la haría pasar por la del
    emisor, y el encabezado del delta la citaría como «la última edición que publicó».

    La naturaleza se lee de `shared/data/series_nature.py`, que es donde se declara.
    """
    from shared.data.series_nature import infer_nature
    from shared.observations import service as obs

    codigos = sorted({r.series for r in records})
    for codigo in codigos:
        obs.borrar_serie(db, sector_key=SECTOR_KEY_OBS, series_code=codigo)
    puntos = {}
    for r in records:
        puntos[(r.series, r.period)] = r   # el último gana, igual que el upsert de la otra tabla
    for (codigo, periodo), r in sorted(puntos.items()):
        obs.upsert(db, sector_key=SECTOR_KEY_OBS, series_code=codigo, period=periodo,
                   value=r.value, unit=r.unit, frequency="monthly",
                   nature=infer_nature(r.unit, code=codigo), source=source,
                   license=license, published_at=None)
    return len(puntos)


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
    set_phase("Feed mensual SFS (observaciones)")
    observaciones = escribir_observaciones_sfs(db, records, source=client.source,
                                               license=client.license)
    # UNA transacción para las dos tablas: si una no entra, no queda la otra a medias y el
    # guard de convivencia no ve dos versiones del mismo mes.
    db.commit()
    set_phase("Completado")
    return {"sfs_rows": rows, "observaciones": observaciones, "source": client.source,
            "mode": used}
