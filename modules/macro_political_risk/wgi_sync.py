"""WGI sync — persist live World Bank governance data into the IRMP store.

Fetches the three WGI 0-100 governance scores for the regional peer set and
upserts them into ``mpr_country_variables`` (idempotent by country/period/var),
so the IRMP dataset is assembled from real data instead of fixtures.
"""
import logging
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from modules.macro_political_risk.models.models import CountryVariable

logger = logging.getLogger("sdq.mpr.wgi_sync")


def wgi_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Pull live WGI for the peer set and upsert. Returns a summary with errors[]."""
    set_phase = set_phase or (lambda _m: None)
    from shared.data.wgi_client import WGIClient

    set_phase("consultando WGI (Banco Mundial)")
    client = WGIClient(mode="live")
    try:
        records = client.fetch()
    except Exception as e:  # noqa: BLE001 — best-effort; report, don't crash the op
        logger.warning("WGI sync falló: %s", e)
        return {"error": f"WGI no disponible: {e}", "synced": 0, "errors": [str(e)]}

    set_phase(f"persistiendo {len(records)} valores")
    synced = 0
    periods = set()
    errors = []
    for r in records:
        iso, var, period = r.dimension, r.series, r.period
        if not iso or not period:
            errors.append(f"registro sin país/período: {var}")
            continue
        periods.add(period)
        existing = (
            db.query(CountryVariable)
            .filter_by(iso_code=iso, period=period, variable=var)
            .first()
        )
        row = existing or CountryVariable(iso_code=iso, period=period, variable=var, source="WGI")
        row.value = r.value
        row.source = "WGI"
        if not existing:
            db.add(row)
        synced += 1
    db.commit()
    return {
        "synced": synced,
        "periods": sorted(periods),
        "countries": len({r.dimension for r in records if r.dimension}),
        "variables": sorted({r.series for r in records}),
        "errors": errors,
    }
