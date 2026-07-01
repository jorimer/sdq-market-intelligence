"""WDI/IMF sync — persist live World Bank + IMF macro data into the IRMP store.

Fetches the macro/external IRMP inputs for the regional peer set and upserts them
into ``mpr_country_variables`` (idempotent by country/period/variable), so the
IRMP runs on real data instead of fixtures. Mirrors :mod:`wgi_sync`. Each value
keeps its upstream in ``CountryVariable.source`` ("WDI" or "IMF_WEO").
"""
import logging
from datetime import date
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from modules.macro_political_risk.models.models import CountryVariable

logger = logging.getLogger("sdq.mpr.wdi_sync")


def wdi_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Pull live WDI+IMF for the peer set and upsert. Returns a summary with errors[]."""
    set_phase = set_phase or (lambda _m: None)
    from shared.data.wdi_client import WDIClient

    set_phase("consultando WDI (Banco Mundial) + IMF WEO")
    client = WDIClient(mode="live")
    try:
        records = list(client.fetch())
    except Exception as e:  # noqa: BLE001 — best-effort; report, don't crash the op
        logger.warning("WDI/IMF sync falló: %s", e)
        return {"error": f"WDI/IMF no disponible: {e}", "synced": 0, "errors": [str(e)]}

    # Declared sovereign_rating_score (doctrine table), stamped at the live data's
    # reference period so it aligns with WDI/IMF in a snapshot.
    from shared.data.wdi_client import declared_sovereign_records
    live_periods = [r.period for r in records if r.period]
    ref_period = max(live_periods) if live_periods else str(date.today().year)
    records += declared_sovereign_records(ref_period, db=db)

    set_phase(f"persistiendo {len(records)} valores")
    synced = 0
    periods = set()
    errors = []
    for r in records:
        iso, var, period = r.dimension, r.series, r.period
        src = r.lineage.source if r.lineage else "WDI"
        if not iso or not period:
            errors.append(f"registro sin país/período: {var}")
            continue
        periods.add(period)
        existing = (
            db.query(CountryVariable)
            .filter_by(iso_code=iso, period=period, variable=var)
            .first()
        )
        row = existing or CountryVariable(iso_code=iso, period=period, variable=var, source=src)
        row.value = r.value
        row.source = src
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
