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

# National labour (ONE/BCRD ENCFT) → applied to every region, like WDI health.
# informality_rate = exact IDM variable; income_per_capita = declared PROXY
# (hourly labour income, not household per-capita income).
_LABOR_UNITS = {
    "informality_rate": "% de la población ocupada",
    "income_per_capita": "RD$/hora (proxy: ingreso laboral)",
}
COVERAGE_THEME = "secondary_coverage"  # ONE net secondary-coverage by region + period
COVERAGE_UNIT = "% (cobertura neta secundaria)"  # ≤40 chars: sd_indicators.unit VARCHAR(40)

# National financial inclusion (World Bank Findex): ATMs per 100k adults — an annual
# access PROXY (denser than the sparse account-ownership survey). Closes the IDM's
# last rubric variable. National, applied to every region like WDI health.
WB_FINDEX = {"FB.ATM.TOTL.P5": "financial_inclusion"}
FINDEX_UNIT = "cajeros/100k (proxy acceso BM)"  # ≤40 chars: sd_indicators.unit
_WB_FINDEX_YEARS = 25  # ATMs/100k spans 2004-2023 (≤25)


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


def _sync_one_labor(db: Session, set_phase: Callable[[str], None]) -> int:
    """Fetch national ONE labour series (informality + income proxy) → sd_indicators
    (entity ``nacional``, applied to every region in the assembly). Best-effort."""
    from shared.data.one_client import fetch_one_labor

    set_phase("trabajo nacional (ONE: informalidad + ingreso)")
    try:
        rows = fetch_one_labor()
    except Exception as e:  # noqa: BLE001 — best-effort; report, don't crash the op
        logger.warning("[social] ONE labour sync falló: %s", e)
        return 0
    synced = 0
    for theme, year, value in rows:
        _upsert_indicator(db, theme=theme, entity=HEALTH_ENTITY, period=str(year),
                          value=float(value), source="ONE",
                          disagg="nacional", unit=_LABOR_UNITS.get(theme))
        synced += 1
    return synced


def _sync_one_coverage(db: Session, set_phase: Callable[[str], None]) -> int:
    """Fetch ONE net secondary-coverage by the 10 development regions (2010-2024) →
    sd_indicators (by region + period, like poverty). Best-effort."""
    from shared.data.one_client import fetch_one_education_coverage

    set_phase("cobertura educativa por región (ONE: secundaria)")
    try:
        rows = fetch_one_education_coverage()
    except Exception as e:  # noqa: BLE001 — best-effort; report, don't crash the op
        logger.warning("[social] ONE coverage sync falló: %s", e)
        return 0
    synced = 0
    for region_slug, year, value in rows:
        _upsert_indicator(db, theme=COVERAGE_THEME, entity=region_slug, period=str(year),
                          value=float(value), source="ONE", disagg="region", unit=COVERAGE_UNIT)
        synced += 1
    return synced


def _sync_wb_findex(db: Session, set_phase: Callable[[str], None]) -> int:
    """Fetch World Bank Findex financial-access (ATMs/100k adults) → sd_indicators
    (entity ``nacional``, applied to every region). Best-effort."""
    from shared.data.wdi_client import fetch_wb_indicator

    set_phase("inclusión financiera nacional (BM Findex: cajeros/100k)")
    synced = 0
    for code, theme in WB_FINDEX.items():
        try:
            rows, _ = fetch_wb_indicator(code, ["DOM"], mrv=_WB_FINDEX_YEARS)
        except Exception as e:  # noqa: BLE001 — best-effort per indicator
            logger.warning("[social] BM Findex %s falló: %s", code, e)
            continue
        for r in rows:
            yr, val = r.get("date"), r.get("value")
            if not yr or val is None:
                continue
            _upsert_indicator(db, theme=theme, entity=HEALTH_ENTITY, period=str(yr),
                              value=float(val), source="WB", disagg="nacional", unit=FINDEX_UNIT)
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
    labor_synced = _sync_one_labor(db, set_phase)
    coverage_synced = _sync_one_coverage(db, set_phase)
    findex_synced = _sync_wb_findex(db, set_phase)
    db.commit()
    return {
        "synced": synced,
        "health_synced": health_synced,
        "labor_synced": labor_synced,
        "coverage_synced": coverage_synced,
        "findex_synced": findex_synced,
        "periods": sorted(periods),
        "regions": len({r.dimension for r in records if r.dimension}),
        "themes": (sorted({r.series for r in records})
                   + sorted(set(WDI_HEALTH.values()))
                   + sorted(_LABOR_UNITS.keys())
                   + [COVERAGE_THEME]
                   + sorted(WB_FINDEX.values())),
        "errors": errors,
    }
