"""ONE social sync — persist live ONE statistics into the social store.

Pulls the real ONE data (first: poverty by development region) and upserts it into
``sd_indicators`` (idempotent by entity_key/theme/period), so the IDM runs on real
data instead of the illustrative regions. Mirrors
:mod:`modules.sector_intel.sectors_sync`.
"""
import logging
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.social_dev.models.models import SocialIndicator
from shared.data.siuben_client import DATASETS as SIUBEN_DATASETS
from shared.data.siuben_client import SOURCE as SIUBEN_SOURCE

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

# Series PROVINCIALES (SIUBEN, 32 provincias). Se derivan del catálogo del conector
# para que el resumen de la operación liste lo que realmente sincronizó.
SIUBEN_THEMES = tuple(s.theme for s in SIUBEN_DATASETS)

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


def _sync_bcrd_informality(db: Session, set_phase: Callable[[str], None]) -> int:
    """Informalidad laboral desde la FUENTE PRIMARIA (ENCFT del BCRD, CDN público).

    Reemplaza el raspado de la landing de la ONE, que dejó de funcionar cuando el
    portal quedó tras un desafío de Cloudflare. La ONE no producía este dato: lo
    republicaba. Verificado contra la serie anterior — 55.47% contra 55.46% en 2024,
    coinciden en la centésima, así que es el mismo indicador y no uno parecido."""
    from shared.data.bcrd_labor import LICENSE, SOURCE, fetch_bcrd_informality

    set_phase("informalidad laboral (BCRD · ENCFT)")
    rows = fetch_bcrd_informality()   # la excepción sube a _best_effort
    synced = 0
    for year, value in rows:
        _upsert_indicator(db, theme="informality_rate", entity=HEALTH_ENTITY,
                          period=str(year), value=float(value), source=SOURCE,
                          disagg="nacional", unit=_LABOR_UNITS["informality_rate"])
        synced += 1
    logger.info("[social] informalidad BCRD: %d años (%s)", synced, LICENSE[:40])
    return synced


def _sync_one_labor(db: Session, set_phase: Callable[[str], None]) -> int:
    """Ingreso laboral promedio (ONE) → sd_indicators (entity ``nacional``).

    Queda SOLO el ingreso: la informalidad pasó al BCRD, que es quien la produce. El
    BCRD publica los deciles de ingreso como CONTEOS de perceptores, no como montos, así
    que el ingreso laboral promedio no tiene sustituto primario y sigue dependiendo de
    la ONE — hoy inalcanzable. La falla se declara en ``errors`` en vez de esconderse:
    el dato ya cargado no se pierde (el upsert no borra), pero deja de refrescarse."""
    from shared.data.one_client import fetch_one_labor

    set_phase("ingreso laboral nacional (ONE)")
    rows = fetch_one_labor()   # la excepción sube a _best_effort, que la DECLARA
    synced = 0
    for theme, year, value in rows:
        if theme != "income_per_capita":
            continue          # la informalidad ya vino del BCRD; no se pisa
        _upsert_indicator(db, theme=theme, entity=HEALTH_ENTITY, period=str(year),
                          value=float(value), source="ONE",
                          disagg="nacional", unit=_LABOR_UNITS.get(theme))
        synced += 1
    return synced


def _sync_minerd_coverage(db: Session, set_phase: Callable[[str], None]) -> int:
    """Cobertura neta de secundaria por región Y por provincia → ``sd_indicators``.

    La fuente pasó de la planilla de la ONE al tablero del MINERD, que es quien produce
    el indicador: la ONE lo republicaba y su portal quedó tras un desafío de Cloudflare.
    El cambio también trae el desglose PROVINCIAL, que la planilla tenía y el parser
    anterior descartaba.

    Los dos niveles comparten el tema ``secondary_coverage`` y se distinguen por
    ``disaggregation``; los slugs provinciales nunca chocan con los regionales (fijado en
    ``shared/reference/tests/test_provinces.py``). Solo las filas regionales llegan al
    IDM: :func:`assemble_idm_dataset` itera el catálogo de regiones, así que agregar
    provincias no puede mover un score."""
    from shared.data.minerd_coverage import SOURCE as MINERD_SOURCE
    from shared.data.minerd_coverage import fetch_minerd_coverage

    set_phase("cobertura educativa por región y provincia (MINERD · SIIE)")
    rows = fetch_minerd_coverage()   # la excepción sube a _best_effort
    synced = 0
    for level, slug, year, value in rows:
        _upsert_indicator(db, theme=COVERAGE_THEME, entity=slug, period=str(year),
                          value=float(value), source=MINERD_SOURCE, disagg=level,
                          unit=COVERAGE_UNIT)
        synced += 1
    return synced


def _sync_siuben_provincial(db: Session, set_phase: Callable[[str], None]) -> int:
    """Fetch the five SIUBEN provincial boards (32 provinces, quarterly since 2017) →
    ``sd_indicators`` with ``disaggregation='provincia'``.

    This is the first SUB-NATIONAL source of the axis. It does NOT feed the IDM: the
    index is assembled strictly over the 10 development regions
    (:func:`assemble_idm_dataset` iterates ``region_catalog()``), so these rows are
    additive and cannot shift a regional score. They exist to be served on their own —
    a consumer that ranks demarcations needs values that differ BETWEEN demarcations,
    which a national constant can never provide.

    The universe (the SIUBEN targeting registry, not the general population) travels in
    the series code and unit; see :mod:`shared.data.siuben_client`. Best-effort."""
    from shared.data.siuben_client import fetch_siuben_provincial, theme_spec

    set_phase("indicadores provinciales (SIUBEN: 32 provincias)")
    rows = fetch_siuben_provincial()   # la excepción sube a _best_effort
    if not rows:
        return 0

    # Prefetch instead of one SELECT per row: five boards × 32 provinces × ~38 quarters
    # is a few thousand upserts, and a round-trip each would make a background sync
    # needlessly slow against a remote Postgres.
    existing = {
        # ``str(...)`` en la frontera: estos modelos usan el estilo legacy de SQLAlchemy,
        # cuyo tipo estático es ``Column[str]`` y no ``str``.
        (str(r.entity_key), str(r.theme), str(r.period)): r
        for r in db.query(SocialIndicator).filter(SocialIndicator.source == SIUBEN_SOURCE).all()
    }
    synced = 0
    for theme, slug, period, value in rows:
        spec = theme_spec(theme)
        key = (slug, theme, period)
        row = existing.get(key)
        if row is None:
            row = SocialIndicator(theme=theme, entity_key=slug, period=period)
            db.add(row)
            existing[key] = row
        _apply_siuben_fields(row, value=value, unit=spec.unit if spec else None)
        synced += 1
    return synced


def _apply_siuben_fields(row, *, value: float, unit) -> None:
    """Asigna los campos de una observación del SIUBEN (frontera con el modelo legacy)."""
    row.value = float(value)
    row.unit = unit
    row.disaggregation = "provincia"
    row.source = SIUBEN_SOURCE


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


def _sync_one_schooling(db: Session, set_phase: Callable[[str], None]) -> int:
    """Fetch ONE national average years of schooling (15+, 2000-2024) → sd_indicators
    (entity ``nacional``, period-matched). ENHOGAR only has literacy by region, not
    years of schooling, so this comes from the national ONE series. Best-effort."""
    from shared.data.one_client import fetch_one_education_schooling

    set_phase("escolaridad nacional (ONE: años promedio de educación)")
    rows = fetch_one_education_schooling()   # la excepción sube a _best_effort
    synced = 0
    for year, value in rows:
        _upsert_indicator(db, theme="schooling_years", entity=HEALTH_ENTITY, period=str(year),
                          value=float(value), source="ONE", disagg="nacional", unit="años")
        synced += 1
    return synced


def _best_effort(label: str, fn: Callable[[], int], errors: List[str]) -> int:
    """Corre una sub-sincronización y DEJA RASTRO de por qué no trajo nada.

    Antes cada sub-sync se tragaba su excepción y devolvía 0, así que la operación
    terminaba con cuatro fuentes en cero y ``errors: []`` — un éxito aparente. Pasó de
    verdad: el 2026-08-09 el portal de la ONE y el SIUBEN devolvieron cero desde
    producción y la consola no lo dijo. Un guard que no reporta no protege: esconde.

    Las dos causas se distinguen a propósito, porque se actúan distinto:

    * **no se pudo llegar** (excepción) → problema nuestro o de red: hay que investigar;
    * **la fuente no devolvió nada** (cero sin excepción) → puede ser legítimo (el emisor
      no publicó todavía) y no amerita alarma, pero tiene que constar.
    """
    try:
        n = fn()
    except Exception as e:  # noqa: BLE001 — best-effort, pero NUNCA silencioso
        logger.warning("[social] %s falló: %s", label, e)
        errors.append(f"{label}: no se pudo obtener el dato ({type(e).__name__}: {e})")
        return 0
    if n == 0:
        errors.append(f"{label}: la fuente respondió sin observaciones")
    return n


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
    health_synced = _best_effort(
        "salud nacional (WDI)", lambda: _sync_wdi_health(db, set_phase), errors)
    informality_synced = _best_effort(
        "informalidad laboral (BCRD · ENCFT)",
        lambda: _sync_bcrd_informality(db, set_phase), errors)
    labor_synced = _best_effort(
        "ingreso laboral (ONE)", lambda: _sync_one_labor(db, set_phase), errors)
    # El rótulo nombra al EMISOR, porque es lo que se lee en la consola cuando algo
    # falla: decir "(ONE)" de un dato que ahora produce el MINERD mandaría a mirar el
    # portal equivocado.
    coverage_synced = _best_effort(
        "cobertura educativa (MINERD · SIIE)",
        lambda: _sync_minerd_coverage(db, set_phase), errors)
    schooling_synced = _best_effort(
        "escolaridad nacional (ONE)", lambda: _sync_one_schooling(db, set_phase), errors)
    findex_synced = _best_effort(
        "inclusión financiera (BM Findex)", lambda: _sync_wb_findex(db, set_phase), errors)
    provincial_synced = _best_effort(
        "indicadores provinciales (SIUBEN)",
        lambda: _sync_siuben_provincial(db, set_phase), errors)
    db.commit()
    return {
        "synced": synced,
        "health_synced": health_synced,
        "informality_synced": informality_synced,
        "labor_synced": labor_synced,
        "coverage_synced": coverage_synced,
        "schooling_synced": schooling_synced,
        "findex_synced": findex_synced,
        "provincial_synced": provincial_synced,
        "periods": sorted(periods),
        "regions": len({r.dimension for r in records if r.dimension}),
        "themes": (sorted({r.series for r in records})
                   + sorted(set(WDI_HEALTH.values()))
                   + sorted(_LABOR_UNITS.keys())
                   + [COVERAGE_THEME, "schooling_years"]
                   + sorted(WB_FINDEX.values())
                   + sorted(SIUBEN_THEMES)),
        "errors": errors,
    }
