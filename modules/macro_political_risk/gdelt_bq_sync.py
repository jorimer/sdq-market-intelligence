"""GDELT-BigQuery sync — persist live events signals into the IRMP store.

Robust alternative to the rate-limited DOC API: one BigQuery query yields tone +
protest + sanctions shares for the peer set. Upserts into ``mpr_country_variables``
(source ``GDELT_BQ``), stamped at the existing data vintage; skips None so the
declared rubric stays the fallback (never fabricated). Best-effort.
"""
import logging
from datetime import date
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from modules.macro_political_risk.models.models import CountryVariable

logger = logging.getLogger("sdq.mpr.gdelt_bq_sync")


def gdelt_bq_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Pull events signals from GDELT-BigQuery for the peer set and upsert."""
    set_phase = set_phase or (lambda _m: None)
    from shared.data.gdelt_bq_client import fetch_events

    set_phase("consultando GDELT vía BigQuery (gkg particionado)")
    try:
        records = fetch_events()
    except Exception as e:  # noqa: BLE001 — best-effort; report, don't crash the op
        logger.warning("GDELT-BQ sync falló: %s", e)
        return {"error": f"GDELT-BQ no disponible: {e}", "synced": 0, "errors": [str(e)]}

    ref = (
        db.query(CountryVariable.period)
        .filter(CountryVariable.source.notin_(["GDELT", "GDELT_BQ"]))
        .order_by(CountryVariable.period.desc())
        .limit(1)
        .scalar()
    ) or str(date.today().year)

    set_phase(f"persistiendo señales de eventos (período {ref})")
    synced, skipped, errors = 0, 0, []
    for r in records:
        iso, var = r.dimension, r.series
        if not iso:
            errors.append(f"registro sin país: {var}")
            continue
        if r.value is None:  # gap → keep the declared rubric, never null-overwrite
            skipped += 1
            continue
        existing = (
            db.query(CountryVariable)
            .filter_by(iso_code=iso, period=ref, variable=var)
            .first()
        )
        row = existing or CountryVariable(iso_code=iso, period=ref, variable=var, source="GDELT_BQ")
        row.value = r.value
        row.source = "GDELT_BQ"
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
