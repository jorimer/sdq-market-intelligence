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

# National health (WDI) → applied to every region (no by-region source yet).
WDI_HEALTH = {"SP.DYN.LE00.IN": "life_expectancy", "SP.DYN.IMRT.IN": "child_mortality"}
HEALTH_ENTITY = "nacional"
_WDI_HEALTH_YEARS = 30


def _upsert_indicator(db: Session, *, theme, entity, period, value, source, disagg, unit) -> None:
    existing = (
        db.query(SocialIndicator)
        .filter_by(entity_key=entity, theme=theme, period=period)
        .first()
    )
    row = existing or SocialIndicator(theme=theme, entity_key=entity, period=period)
    row.value = value
    row.unit = unit
    row.disaggregation = disagg
    row.source = source
    if not existing:
        db.add(row)


def _sync_wdi_health(db: Session, set_phase: Callable[[str], None]) -> int:
    """Fetch DO national life-expectancy + infant-mortality from WDI → sd_indicators
    (entity ``nacional``). National, so applied to every region in the assembly."""
    from shared.data.wdi_client import fetch_wb_indicator

    set_phase("salud nacional (WDI)")
    synced = 0
    for code, theme in WDI_HEALTH.items():
        try:
            rows, _ = fetch_wb_indicator(code, ["DOM"], mrv=_WDI_HEALTH_YEARS)
        except Exception as e:  # noqa: BLE001 — best-effort per indicator
            logger.warning("[social] WDI %s falló: %s", code, e)
            continue
        unit = "años" if theme == "life_expectancy" else "por 1.000 nacidos vivos"
        for r in rows:
            yr, val = r.get("date"), r.get("value")
            if not yr or val is None:
                continue
            _upsert_indicator(db, theme=theme, entity=HEALTH_ENTITY, period=str(yr),
                              value=float(val), source="WDI", disagg="nacional", unit=unit)
            synced += 1
    return synced


def one_social_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Pull live social data (ONE poverty by region + WDI national health) and
    upsert into ``sd_indicators``. Best-effort; never raises on an upstream failure.
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
        _upsert_indicator(db, theme=theme, entity=region, period=period,
                          value=r.value, source="ONE", disagg="region", unit=r.unit)
        synced += 1
    health_synced = _sync_wdi_health(db, set_phase)
    db.commit()
    return {
        "synced": synced,
        "health_synced": health_synced,
        "periods": sorted(periods),
        "regions": len({r.dimension for r in records if r.dimension}),
        "themes": sorted({r.series for r in records}) + sorted(set(WDI_HEALTH.values())),
        "errors": errors,
    }
