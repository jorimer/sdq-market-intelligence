"""BCRD sectors sync — persist live value-added data into the sector store.

Pulls ``sector_size`` + ``sector_growth`` for the full-economy leaf sectors from
the BCRD PIB-origen workbook and upserts them into ``si_variables`` (idempotent
by sector/period/variable), so the IAI can run on real sector data instead of
the 3-anchor fixture. Mirrors :mod:`modules.macro_political_risk.wdi_sync`.
"""
import logging
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from modules.sector_intel.models.models import SectorVariable

logger = logging.getLogger("sdq.sector_intel.sectors_sync")

SECTOR_DIMENSION = "sector"  # IAI dimension these variables belong to


def bcrd_sectores_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Pull live BCRD value-added and upsert into ``si_variables``.

    Returns a console summary with ``errors[]``; never raises on an upstream
    failure (best-effort, like the other syncs).
    """
    set_phase = set_phase or (lambda _m: None)
    from shared.data.bcrd_sectors import BCRDSectorsClient
    from modules.sector_intel.service import seed_sectors

    set_phase("sembrando sectores")
    seeded = seed_sectors(db)

    set_phase("descargando PIB por sectores de origen (BCRD)")
    client = BCRDSectorsClient(mode="live")
    try:
        records = list(client.fetch())
    except Exception as e:  # noqa: BLE001 — best-effort; report, don't crash the op
        logger.warning("BCRD sectores sync falló: %s", e)
        return {"error": f"BCRD sectores no disponible: {e}", "synced": 0,
                "sectors_seeded": seeded, "errors": [str(e)]}

    set_phase(f"persistiendo {len(records)} valores")
    synced = 0
    periods = set()
    errors = []
    for r in records:
        slug, var, period = r.dimension, r.series, r.period
        if not slug or not period:
            errors.append(f"registro sin sector/período: {var}")
            continue
        periods.add(period)
        existing = (
            db.query(SectorVariable)
            .filter_by(sector_code=slug, period=period, variable=var)
            .first()
        )
        row = existing or SectorVariable(
            sector_code=slug, dimension=SECTOR_DIMENSION, variable=var, period=period,
        )
        row.value = r.value
        row.dimension = SECTOR_DIMENSION
        row.source = r.lineage.source if r.lineage else "BCRD"
        row.published_at = r.lineage.published_at if r.lineage else None
        row.license = r.lineage.license if r.lineage else None
        if not existing:
            db.add(row)
        synced += 1
    db.commit()
    return {
        "synced": synced,
        "sectors_seeded": seeded,
        "periods": sorted(periods),
        "sectors": len({r.dimension for r in records if r.dimension}),
        "variables": sorted({r.series for r in records}),
        "errors": errors,
    }
