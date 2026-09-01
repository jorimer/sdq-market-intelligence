"""BCRD sectors sync — persist live value-added data into the sector store.

Pulls ``sector_size`` + ``sector_growth`` for the full-economy leaf sectors from
the BCRD PIB-origen workbook and upserts them into ``si_variables`` (idempotent
by sector/period/variable), so the IAI can run on real sector data instead of
the 3-anchor fixture. Mirrors :mod:`modules.macro_political_risk.wdi_sync`.
"""
import logging
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.reference.sector_variables import (  # noqa: F401 — re-export
    ENAE_DIMENSION, IED_DIMENSION, LABOR_ENCFT_DIMENSION, SECTOR_DIMENSION,
    SectorVariable,
)

logger = logging.getLogger("sdq.sector_intel.sectors_sync")

# El archivo vigente del BCRD arranca en 2018; el retropolado extiende a 2007. Si el
# panel trae algún año ≤ este ancla, el vintage histórico se ingirió; si arranca en
# 2018+, el retropolado no estaba disponible (degradación a rotular, no silenciar).
_RETRO_HISTORY_ANCHOR_YEAR = 2017
# Las cuatro dimensiones de `si_variables` —y qué resolución es cada una— se declaran
# junto al modelo, en `shared/reference/sector_variables.py`.

# TSS salary → operating_cost is a CROSS-SECTIONAL snapshot (per-slug, applied
# uniformly across periods like the national WGI), so it lives as an AppSetting the
# IAI assembly reads, not as per-period si_variables rows.
OPERATING_COST_KEY = "sector_operating_cost"


def latest_complete_year(years, current_year: int) -> Optional[str]:
    """Latest year in *years* that is not the in-progress *current_year*.

    The TSS report carries the current (partial) calendar year; prefer the latest
    completed year for a stable snapshot, falling back to the max if that's all
    there is. Pure/testable.
    """
    ys = sorted({int(y) for y in years})
    if not ys:
        return None
    complete = [y for y in ys if y < current_year]
    return str(complete[-1] if complete else ys[-1])

# WGI regulatory quality is NATIONAL (one value for the country, not per sector), so
# it's stored as a national AppSetting series and applied uniformly to every sector
# in the IAI assembly — like the macro→sectorial contract. It makes the regulation
# dimension real (vs declared rubric) but, being uniform across sectors, does not
# change the cross-sectional ranking (it normalizes to neutral).
WGI_REGULATORY_KEY = "sector_regulatory_wgi"
WGI_RQ_CODE = "GOV_WGI_RQ.SC"


def wgi_regulatory_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Fetch the national WGI regulatory-quality series (DOM, 0-100 percentile) and
    persist it as an AppSetting the IAI assembly reads. Best-effort."""
    import json

    from shared.data.wgi_client import fetch_wgi_indicator
    from shared.settings.models import AppSetting

    set_phase = set_phase or (lambda _m: None)
    set_phase("descargando calidad regulatoria nacional (WGI)")
    try:
        rows, last_updated = fetch_wgi_indicator(WGI_RQ_CODE, ["DOM"], mrv=12)
    except Exception as e:  # noqa: BLE001 — best-effort; report, don't crash the op
        logger.warning("WGI regulatory sync falló: %s", e)
        return {"error": str(e), "years": 0, "errors": [str(e)]}

    series = {str(r["date"]): float(r["value"]) for r in rows
              if r.get("date") and r.get("value") is not None}
    payload = {"series": series, "unit": "percentil 0-100", "source": "WGI",
               "last_updated": last_updated}
    row = db.query(AppSetting).filter(AppSetting.key == WGI_REGULATORY_KEY).first()
    if row:
        row.value = json.dumps(payload)
    else:
        db.add(AppSetting(key=WGI_REGULATORY_KEY, value=json.dumps(payload), is_secret=False))
    db.commit()
    years = sorted(series)
    return {"years": len(series), "range": [years[0], years[-1]] if years else None,
            "latest": series.get(years[-1]) if years else None, "errors": []}


# Human Capital Index (WB, HD.HCI.OVRL) — NACIONAL (un valor por país), como la WGI
# regulatoria. Fuente real para la dimensión talento del IAI (skills_index), que hoy es
# rúbrica. Uniforme entre sectores: sube la procedencia a dato real, no cambia el ranking
# (normaliza al centro). El HCI viene 0-1 → se escala ×100 a la escala 0-100 del IAI.
HUMAN_CAPITAL_KEY = "sector_skills_hci"
HCI_CODE = "HD.HCI.OVRL"


def human_capital_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Fetch the national WB Human Capital Index (DOM) and persist it, scaled 0-100, as
    the AppSetting the IAI assembly reads for ``skills_index``. Best-effort."""
    import json

    from shared.data.wgi_client import fetch_wgi_indicator  # fetcher WB genérico
    from shared.settings.models import AppSetting

    set_phase = set_phase or (lambda _m: None)
    set_phase("descargando capital humano nacional (WB HCI)")
    try:
        rows, last_updated = fetch_wgi_indicator(HCI_CODE, ["DOM"], mrv=8)
    except Exception as e:  # noqa: BLE001 — best-effort; report, don't crash the op
        logger.warning("HCI sync falló: %s", e)
        return {"error": str(e), "years": 0, "errors": [str(e)]}

    # HCI ∈ [0,1] → escala 0-100 (misma que skills_index).
    series = {str(r["date"]): round(float(r["value"]) * 100.0, 2) for r in rows
              if r.get("date") and r.get("value") is not None}
    payload = {"series": series, "unit": "índice 0-100 (HCI×100)", "source": "WB-HCI",
               "last_updated": last_updated}
    row = db.query(AppSetting).filter(AppSetting.key == HUMAN_CAPITAL_KEY).first()
    if row:
        row.value = json.dumps(payload)
    else:
        db.add(AppSetting(key=HUMAN_CAPITAL_KEY, value=json.dumps(payload), is_secret=False))
    db.commit()
    years = sorted(series)
    return {"years": len(series), "range": [years[0], years[-1]] if years else None,
            "latest": series.get(years[-1]) if years else None, "errors": []}


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
            .filter_by(sector_code=slug, dimension=SECTOR_DIMENSION, period=period, variable=var)
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
    # Visibilidad del vintage histórico (retropolado 2007+). Es best-effort en el
    # conector: si el CDN del BCRD renombra el archivo (lección IPoM), la sync cae a
    # solo-vigente (2018+) SIN fallar. Para que esa degradación no sea silenciosa, se
    # infiere del rango del panel y se rota a errors[] (que el console/freshness resalta).
    years = sorted({int(p) for p in periods if str(p).isdigit()})
    rng = [years[0], years[-1]] if years else None
    historical_ok = bool(years and years[0] <= _RETRO_HISTORY_ANCHOR_YEAR)
    if years and not historical_ok:
        errors.append(
            f"histórico retropolado (2007+) no disponible: el panel arranca en {years[0]} "
            "— el BCRD pudo renombrar 'pib_origen_retro_2018_2007.xlsx' (revisar el CDN)"
        )
    return {
        "synced": synced,
        "sectors_seeded": seeded,
        "periods": sorted(periods),
        "range": rng,
        "historical": "included" if historical_ok else "unavailable",
        "sectors": len({r.dimension for r in records if r.dimension}),
        "variables": sorted({r.series for r in records}),
        "errors": errors,
    }


def encft_empleo_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Pull live ONE/ENCFT employment by activity branch and upsert into ``si_variables``.

    Persists the real, point-in-time employment panel (10 ONE branches, ENFT
    2008-2016 / ENCFT 2017-2024) under ``dimension="labor_encft"`` — the Gate-E
    outcome and the raw input ``labor_availability`` is later derived from. Rows are
    keyed by branch (not the 17 slugs); the IAI never reads this dimension, so the
    17-slug index is untouched. Idempotent by (sector_code, period, variable);
    best-effort (reports ``errors[]``, never raises on an upstream failure).
    """
    set_phase = set_phase or (lambda _m: None)
    from shared.data.encft_employment import EmploymentClient

    set_phase("descargando empleo por actividad económica (ONE · ENCFT)")
    client = EmploymentClient(mode="live")
    try:
        records = list(client.fetch())
    except Exception as e:  # noqa: BLE001 — best-effort; report, don't crash the op
        logger.warning("ENCFT empleo sync falló: %s", e)
        return {"error": f"empleo ENCFT no disponible: {e}", "synced": 0, "errors": [str(e)]}

    set_phase(f"persistiendo {len(records)} valores")
    synced = 0
    periods = set()
    errors = []
    for r in records:
        branch, var, period = r.dimension, r.series, r.period
        if not branch or not period:
            errors.append(f"registro sin rama/período: {var}")
            continue
        periods.add(period)
        existing = (
            db.query(SectorVariable)
            .filter_by(sector_code=branch, dimension=LABOR_ENCFT_DIMENSION,
                       period=period, variable=var)
            .first()
        )
        row = existing or SectorVariable(
            sector_code=branch, dimension=LABOR_ENCFT_DIMENSION, variable=var, period=period,
        )
        row.value = r.value
        row.dimension = LABOR_ENCFT_DIMENSION
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
        "branches": len({r.dimension for r in records if r.dimension}),
        "variables": sorted({r.series for r in records}),
        "errors": errors,
    }


def bcrd_ied_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Ingiere la IED por actividad del BCRD (anual, 2010→) a ``si_variables``.

    Es el desenlace que el IAI SÍ pretende anticipar. El Gate E lo validaba contra empleo
    formal —que el índice no dice anticipar— y daba nulo/negativo; esta serie es inversión
    REALIZADA por actividad, publicada por el propio BCRD.

    Filas keyed por ACTIVIDAD de IED (no por los 17 slugs): repartir el bundle
    «Comercio / Industria» entre comercio y manufactura sería fabricar. Idempotente por
    (sector_code, dimension, period, variable); best-effort (reporta ``errors[]``).
    """
    set_phase = set_phase or (lambda _m: None)
    from shared.data.ied_bcrd import SERIES as IED_SERIES, IedBcrdClient

    set_phase("descargando IED por actividad económica (BCRD)")
    try:
        registros = list(IedBcrdClient(mode="live").fetch())
    except Exception as e:  # noqa: BLE001 — best-effort: reportar, no tumbar la operación
        logger.warning("IED BCRD sync falló, cayendo al fixture comiteado: %s", e)
        try:
            registros = list(IedBcrdClient(mode="fixture").fetch())
        except Exception as e2:  # noqa: BLE001
            return {"error": f"IED no disponible: {e2}", "synced": 0, "errors": [str(e), str(e2)]}

    set_phase(f"persistiendo {len(registros)} valores de IED")
    synced = 0
    periodos = set()
    for r in registros:
        actividad, periodo = r.dimension, r.period
        if not actividad or not periodo:
            continue
        periodos.add(periodo)
        existente = (db.query(SectorVariable)
                     .filter_by(sector_code=actividad, dimension=IED_DIMENSION,
                                period=periodo, variable=IED_SERIES).first())
        fila: Any = existente or SectorVariable(
            sector_code=actividad, dimension=IED_DIMENSION,
            variable=IED_SERIES, period=periodo)
        fila.value = r.value
        fila.source = r.lineage.source if r.lineage else "BCRD"
        fila.license = r.lineage.license if r.lineage else None
        if not existente:
            db.add(fila)
        synced += 1
    db.commit()
    return {"synced": synced, "periods": sorted(periodos),
            "actividades": len({r.dimension for r in registros if r.dimension}), "errors": []}


def enae_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Pull live ONE/ENAE structural-financial tables (income, costs, profit,
    profitability) by survey sector and upsert into ``si_variables``.

    Persists the real per-sector panel (9 ENAE sectors, 2015-2022) under
    ``dimension="enae"`` — keyed by ENAE sector (not the 17 slugs), so the 17-slug
    IAI is untouched. Idempotent by (sector_code, dimension, period, variable);
    best-effort (reports ``errors[]``, never raises on an upstream failure).
    """
    set_phase = set_phase or (lambda _m: None)
    from shared.data.enae_activity import EnaeActivityClient

    set_phase("descargando actividad económica por sector (ONE · ENAE)")
    client = EnaeActivityClient(mode="live")
    try:
        records = list(client.fetch())
    except Exception as e:  # noqa: BLE001 — best-effort; report, don't crash the op
        logger.warning("ENAE sync falló: %s", e)
        return {"error": f"ENAE no disponible: {e}", "synced": 0, "errors": [str(e)]}

    set_phase(f"persistiendo {len(records)} valores")
    synced = 0
    periods = set()
    errors = []
    for r in records:
        sector, var, period = r.dimension, r.series, r.period
        if not sector or not period:
            errors.append(f"registro sin sector/período: {var}")
            continue
        periods.add(period)
        existing = (
            db.query(SectorVariable)
            .filter_by(sector_code=sector, dimension=ENAE_DIMENSION, period=period, variable=var)
            .first()
        )
        row = existing or SectorVariable(
            sector_code=sector, dimension=ENAE_DIMENSION, variable=var, period=period,
        )
        row.value = r.value
        row.dimension = ENAE_DIMENSION
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
        "sectors": len({r.dimension for r in records if r.dimension}),
        "variables": sorted({r.series for r in records}),
        "errors": errors,
    }


def tss_salario_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Fetch TSS salary-by-activity, map to per-slug ``operating_cost`` and persist
    it as the AppSetting the IAI assembly reads. Best-effort.

    The salary is a cross-sectional snapshot (the TSS series only covers recent
    years, the IAI runs 2018-…), so the latest complete year is applied uniformly
    across periods — the WGI pattern. Persisted per BCRD-17 slug (short keys), NOT
    per raw activity (whose key can exceed ``VARCHAR(40)``).
    """
    import json

    from shared.data.sector_crosswalk import salary_by_slug
    from shared.data.tss_salary import TSSSalaryClient, VAR_SALARY
    from shared.settings.models import AppSetting

    set_phase = set_phase or (lambda _m: None)
    set_phase("descargando salario por actividad (TSS · Power BI)")
    client = TSSSalaryClient(mode="live")
    try:
        records = list(client.fetch())
    except Exception as e:  # noqa: BLE001 — best-effort; report, don't crash the op
        logger.warning("TSS salario sync falló: %s", e)
        return {"error": f"salario TSS no disponible: {e}", "slugs": 0, "errors": [str(e)]}

    year = latest_complete_year({r.period for r in records}, date.today().year)
    if not year:
        return {"error": "el reporte TSS no trajo años", "slugs": 0, "errors": ["sin años"]}

    activity_salary = {r.dimension: r.value for r in records
                       if r.period == year and r.series == VAR_SALARY and r.value is not None}
    by_slug = salary_by_slug(activity_salary)
    series: Dict[str, float] = {slug: v for slug, v in by_slug.items() if v is not None}
    missing: List[str] = sorted(slug for slug, v in by_slug.items() if v is None)

    payload = {"series": series, "year": year, "unit": "RD$/mes (salario promedio cotizable)",
               "source": "TSS"}
    row = db.query(AppSetting).filter(AppSetting.key == OPERATING_COST_KEY).first()
    if row:
        row.value = json.dumps(payload)
    else:
        db.add(AppSetting(key=OPERATING_COST_KEY, value=json.dumps(payload), is_secret=False))
    db.commit()
    return {"slugs": len(series), "year": year, "missing": missing,
            "activities": len(activity_salary), "errors": []}
