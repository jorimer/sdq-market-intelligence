"""Backfill histórico del IRMP — trayectoria multi-período con dato 100% real.

El snapshot en vivo (``irmp-snapshot``) calcula el período ACTUAL. Este backfill
reconstruye y persiste un IRMPSnapshot por AÑO para el panel, dándole trayectoria al
producto (antes: un solo corte). Todas las dimensiones con dato real por año:

  * macro / externo ← WDI + IMF WEO multi-año (reusa el fetch del backtest)
  * gobernanza      ← WGI 1996-2024 (serie por año)
  * regulatoria     ← calidad WGI + volatilidad = std de la serie [Y-4, Y]
  * eventos         ← GDELT-BigQuery consultado POR AÑO (no la ventana reciente)
  * electoral       ← proximidad a la próxima elección as-of ese año (calendario)

Es SELF-CONTAINED: no toca el snapshot en vivo ni el panel del backtest (que usa
rúbrica de eventos a propósito, para no volverse circular). Cubre los años PASADOS
(2016 → año anterior); el año actual lo sigue calculando ``irmp-snapshot`` (con GDELT
en vivo + rating soberano). Idempotente por (país, año). El rating soberano no tiene
historia anual usable → se omite en el pasado (la dim externa igual puntúa con cuenta
corriente / IED / volatilidad cambiaria); honesto, no se retro-data el rating actual.
"""
import logging
from datetime import date
from statistics import pstdev
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("sdq.mpr.irmp_backfill")

_START_YEAR = 2016   # GDELT GKG particionado bien cubierto desde ~2015; WDI/WGI también


def _year_row(series: Dict, year: int, iso2: str, targets: Dict[str, float]) -> Dict[str, float]:
    """Fila ``{var: value}`` de macro/externo/gobernanza/regulatoria para *iso2* en
    *year*, desde las series multi-año. Omite lo ausente (nunca fabrica)."""
    from modules.macro_political_risk.validation.historical import (
        IMF_INDICATORS,
        WDI_DIRECT,
        WDI_FX,
        WDI_GDP_LEVEL,
        WDI_INFLATION,
    )
    from shared.data.wdi_client import _cagr, _fx_volatility
    from shared.data.wgi_client import WGI_INDICATORS

    row: Dict[str, float] = {}
    lv = series.get(WDI_GDP_LEVEL, {}).get(iso2, {})
    cagr = _cagr(lv.get(year - 3), lv.get(year), 3)
    if cagr is not None:
        row["gdp_cagr_3y"] = cagr
    infl = series.get(WDI_INFLATION, {}).get(iso2, {}).get(year)
    if infl is not None and iso2 in targets:
        row["inflation_gap"] = round(abs(infl - targets[iso2]), 2)
    fx = {y: v for y, v in series.get(WDI_FX, {}).get(iso2, {}).items() if year - 6 <= y <= year}
    vol = _fx_volatility(fx)
    if vol is not None:
        row["fx_volatility"] = vol
    for code, var in WDI_DIRECT.items():
        v = series.get(code, {}).get(iso2, {}).get(year)
        if v is not None:
            row[var] = v
    for var in list(WGI_INDICATORS.values()) + list(IMF_INDICATORS.values()):
        v = series.get(var, {}).get(iso2, {}).get(year)
        if v is not None:
            row[var] = v
    # regulatory_volatility_5y = std de la calidad regulatoria WGI en [Y-4, Y].
    rq = series.get("wgi_regulatory_quality", {}).get(iso2, {})
    window = [rq[y] for y in range(year - 4, year + 1) if y in rq]
    if len(window) >= 2:
        row["regulatory_volatility_5y"] = round(pstdev(window), 4)
    return row


def _events_for_year(year: int) -> Dict[str, Dict[str, float]]:
    """``{iso2: {news_sentiment, unrest_shocks, sanctions_signal}}`` de GDELT-BQ para
    el año *year*. ``{}`` propagando la excepción al caller (best-effort por año)."""
    from shared.data.gdelt_bq_client import fetch_events_for_year

    out: Dict[str, Dict[str, float]] = {}
    for r in fetch_events_for_year(year):
        if r.value is not None:
            out.setdefault(r.dimension, {})[r.series] = r.value
    return out


def _years_already_done(db: Session, threshold: int) -> set:
    """Años que ya tienen suficientes snapshots persistidos (≥ *threshold*) → un año
    'hecho'. Distingue el año que completó (GDELT ok → ~panel entero) del que falló por
    cuota (0). Permite RESUMIR: no re-consultar GDELT (que gasta cuota) en años ya listos."""
    from collections import Counter

    from modules.macro_political_risk.models.models import IRMPSnapshot

    counts = Counter(pe.year for (pe,) in db.query(IRMPSnapshot.period_end).all() if pe)
    return {y for y, c in counts.items() if c >= threshold}


def backfill_irmp_history(
    db: Session, set_phase: Optional[Callable[[str], None]] = None,
    start_year: int = _START_YEAR, series: Optional[Dict] = None,
    events_by_year: Optional[Dict[int, Dict[str, Dict[str, float]]]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Reconstruye y persiste el IRMP por año (pasado) para todo el panel.

    RESUMIBLE: por defecto salta los años que ya tienen snapshots (sin re-consultar
    GDELT, que consume cuota de BigQuery), así corridas sucesivas (p.ej. mensuales,
    con cuota fresca) van cerrando el hueco hasta completar. ``force=True`` rehace todo.
    *series* / *events_by_year* se inyectan en tests (offline). Devuelve un resumen con
    años, snapshots persistidos, saltados (parciales), ya-hechos (resumidos) y errores."""
    set_phase = set_phase or (lambda _m: None)
    from modules.macro_political_risk.service import (
        _electoral_uncertainty_map,
        compute_and_persist,
    )
    from shared.data.latam_peers import names, regions
    from shared.doctrine import load_doctrine_raw

    end_year = date.today().year - 1  # el año actual lo cubre irmp-snapshot (GDELT live + rating)
    if end_year < start_year:
        return {"years": [start_year, end_year], "persisted": 0, "skipped": 0,
                "resumed": 0, "errors": ["sin años pasados que reconstruir"]}

    targets = load_doctrine_raw("regulatory").get("inflation_targets", {}) or {}
    nm, rg = names(), regions()
    iso2_list = list(nm)
    done_years = set() if force else _years_already_done(db, max(1, len(iso2_list) // 2))
    pending = [y for y in range(start_year, end_year + 1) if y not in done_years]
    if not pending:
        return {"years": [start_year, end_year], "persisted": 0, "skipped": 0,
                "resumed": len(done_years), "errors": [], "note": "trayectoria completa"}

    if series is None:  # pragma: no cover - network I/O
        set_phase("descargando series históricas (WDI + WGI + IMF)")
        from modules.macro_political_risk.validation.historical import fetch_series
        series = fetch_series(mrv=end_year - start_year + 8)  # holgura para CAGR/ventanas

    persisted, skipped, errors = 0, 0, []
    for year in pending:
        if events_by_year is not None:
            events = events_by_year.get(year, {})
        else:  # pragma: no cover - network I/O
            set_phase(f"eventos GDELT {year}")
            try:
                events = _events_for_year(year)
            except Exception as e:  # noqa: BLE001 — un año sin eventos (p.ej. cuota) no aborta
                errors.append(f"{year}: eventos GDELT no disponibles: {e}")
                continue
        electoral = _electoral_uncertainty_map(year)
        dataset: Dict[str, Dict[str, float]] = {}
        for iso2 in iso2_list:
            row = _year_row(series, year, iso2, targets)
            ev = events.get(iso2, {})
            for var in ("news_sentiment", "unrest_shocks", "sanctions_signal"):
                if ev.get(var) is not None:
                    row[var] = ev[var]
            if iso2 in electoral:
                row["electoral_uncertainty"] = electoral[iso2]
            dataset[iso2] = row
        period_end = date(year, 12, 31)
        for iso2 in iso2_list:
            try:
                compute_and_persist(
                    db, country_code=iso2, dataset=dataset, period_end=period_end,
                    country_name=nm.get(iso2), region=rg.get(iso2), publish=False,
                )
                persisted += 1
            except Exception:  # noqa: BLE001 — país-año parcial → saltado (guard), no aborta
                skipped += 1
        set_phase(f"IRMP {year} persistido")

    # Un solo evento al final: que los demás ejes recompongan una vez, no 200+.
    if persisted:
        from modules.macro_political_risk.events import publish_irmp_updated
        publish_irmp_updated({"backfill": True, "years": [start_year, end_year]})
    return {"years": [start_year, end_year], "persisted": persisted,
            "skipped": skipped, "resumed": len(done_years),
            "pending_after": [y for y in pending if y not in _years_already_done(
                db, max(1, len(iso2_list) // 2))],
            "errors": errors[:10]}
