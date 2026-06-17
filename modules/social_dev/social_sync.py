"""ONE social sync — persist live ONE statistics into the social store.

Pulls the real ONE data (first: poverty by development region) and upserts it into
``sd_indicators`` (idempotent by entity_key/theme/period), so the IDM runs on real
data instead of the illustrative regions. Mirrors
:mod:`modules.sector_intel.sectors_sync`.
"""
import logging
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from modules.social_dev.models.models import SocialIndicator

logger = logging.getLogger("sdq.social_dev.one_sync")


def one_social_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Pull live ONE social data and upsert into ``sd_indicators``.

    Returns a console summary with ``errors[]``; best-effort (never raises on an
    upstream failure).
    """
    set_phase = set_phase or (lambda _m: None)
    from shared.data.one_client import ONEClient

    set_phase("descargando pobreza por regiones (ONE)")
    client = ONEClient(mode="live")
    try:
        records = list(client.fetch())
    except Exception as e:  # noqa: BLE001 — best-effort; report, don't crash the op
        logger.warning("ONE social sync falló: %s", e)
        return {"error": f"ONE no disponible: {e}", "synced": 0, "errors": [str(e)]}

    set_phase(f"persistiendo {len(records)} valores")
    synced = 0
    periods = set()
    errors = []
    for r in records:
        region, theme, period = r.dimension, r.series, r.period
        if not region or not period:
            errors.append(f"registro sin región/período: {theme}")
            continue
        periods.add(period)
        existing = (
            db.query(SocialIndicator)
            .filter_by(entity_key=region, theme=theme, period=period)
            .first()
        )
        row = existing or SocialIndicator(
            theme=theme, entity_key=region, period=period, disaggregation="region",
        )
        row.value = r.value
        row.unit = r.unit
        row.disaggregation = "region"
        row.source = r.lineage.source if r.lineage else "ONE"
        row.published_at = r.lineage.published_at if r.lineage else None
        row.license = r.lineage.license if r.lineage else None
        if not existing:
            db.add(row)
        synced += 1
    db.commit()
    return {
        "synced": synced,
        "periods": sorted(periods),
        "regions": len({r.dimension for r in records if r.dimension}),
        "themes": sorted({r.series for r in records}),
        "errors": errors,
    }
