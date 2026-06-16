"""GDELT sync — persist live events signals (tone, unrest) into the IRMP store.

Pulls news_sentiment + unrest_shocks from GDELT for the peer set and upserts them
into ``mpr_country_variables`` (source ``GDELT``). A missing signal is skipped so
the declared rubric value remains the fallback — never fabricated. Values are
stamped at the existing data vintage (the WGI/WDI period) so they align with the
rest in a single snapshot; the actual fetch date is recorded in the lineage.
"""
import logging
from datetime import date
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from modules.macro_political_risk.models.models import CountryVariable

logger = logging.getLogger("sdq.mpr.gdelt_sync")


def gdelt_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Pull live GDELT events signals for the peer set and upsert. Paced + best-effort."""
    set_phase = set_phase or (lambda _m: None)
    from shared.data.gdelt_client import GDELTClient

    set_phase("consultando GDELT (tono + disturbios, con pausas por rate-limit)")
    client = GDELTClient(mode="live")
    try:
        records = client.fetch()
    except Exception as e:  # noqa: BLE001 — best-effort; report, don't crash the op
        logger.warning("GDELT sync falló: %s", e)
        return {"error": f"GDELT no disponible: {e}", "synced": 0, "errors": [str(e)]}

    # Stamp at the existing data vintage so events align with WGI/WDI in a snapshot.
    ref = (
        db.query(CountryVariable.period)
        .filter(CountryVariable.source != "GDELT")
        .order_by(CountryVariable.period.desc())
        .limit(1)
        .scalar()
    ) or str(date.today().year)

    set_phase(f"persistiendo señales GDELT (período {ref})")
    synced, skipped, errors = 0, 0, []
    for r in records:
        iso, var = r.dimension, r.series
        if not iso:
            errors.append(f"registro sin país: {var}")
            continue
        if r.value is None:  # GDELT gap → keep the declared rubric, never null-overwrite
            skipped += 1
            continue
        existing = (
            db.query(CountryVariable)
            .filter_by(iso_code=iso, period=ref, variable=var)
            .first()
        )
        row = existing or CountryVariable(iso_code=iso, period=ref, variable=var, source="GDELT")
        row.value = r.value
        row.source = "GDELT"
        if not existing:
            db.add(row)
        synced += 1
    db.commit()
    return {
        "synced": synced,
        "skipped_missing": skipped,
        "period": ref,
        "countries": len({r.dimension for r in records if r.dimension}),
        "variables": sorted({r.series for r in records}),
        "errors": errors,
    }
