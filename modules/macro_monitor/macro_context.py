"""Macro→sectorial contract producer (Eje 2).

Builds a :class:`MacroSectorContract` from the live BCRD series: for each factor
declared in ``shared/doctrine/macro_sector.yaml`` it reads the named series,
classifies its direction/magnitude against the doctrine thresholds, and tags the
impacted sectors/agents. The sectorial report's §2 "Contexto macro" consumes this
instead of re-deriving macro by hand.

Pure-ish: reads MacroSeries (via the service's grouping) + doctrine; no writes.
Missing series or an uncomputable YoY → an ``n/d`` factor, never a fabricated one.
"""
import logging
from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.contracts.macro_sector import (
    ND,
    MacroFactor,
    MacroSectorContract,
    classify_factor,
    factor_reading,
)
from shared.doctrine import load_doctrine_raw
from modules.macro_monitor.scoring.momentum import compute_series_momentum
from modules.macro_monitor.service import _series_by_code, period_end_date

logger = logging.getLogger("sdq.macro_monitor.macro_context")

Obs = List[Tuple[str, Optional[float]]]
_YOY_TOLERANCE_DAYS = 45  # how close to "one year ago" an obs must be to anchor YoY


def _sector_names() -> Dict[str, str]:
    """slug → display name for the sector catalog (shared, single source)."""
    from shared.data.bcrd_sectors import sector_catalog

    return dict(sector_catalog())


def _yoy_change(clean: List[Tuple[str, float]]) -> Optional[float]:
    """Year-over-year % change of a level series, anchored by period end-dates.

    Frequency-agnostic: finds the observation ~1 year before the latest (within a
    tolerance) and compares. Returns ``None`` when there's no suitable anchor, the
    base is zero, or the series crosses zero between anchor and latest — never
    fabricated.

    Se mide como COCIENTE (``latest/base − 1``), no como ``cambio/|base|``. La forma
    del cociente es sign-correcta para una serie de signo estable aunque sea negativa:
    la FDI de la cuenta financiera (MBP6) es negativa —negativo = entrada neta de
    pasivos— y más entrada la vuelve más negativa; ``−5032/−4523 − 1 = +11,3%`` lee
    correctamente "la entrada CRECIÓ", mientras que ``cambio/|base|`` daría −11,3% y un
    sudden-stop lo leería al revés. Por eso el panel de flujos NO necesita un campo de
    signo: el único caso que el cociente no puede interpretar es el CRUCE DE CERO (la
    entrada se vuelve salida), y ahí se devuelve ``None`` en vez de un porcentaje basura.
    """
    if len(clean) < 2:
        return None
    latest_period, latest_value = clean[-1]
    led = period_end_date(latest_period)
    if led is None:
        return None
    try:
        target = date(led.year - 1, led.month, min(led.day, 28))
    except ValueError:
        return None
    best: Optional[Tuple[int, float]] = None  # (abs day diff, value)
    for p, v in clean[:-1]:
        ed = period_end_date(p)
        if ed is None:
            continue
        diff = abs((ed - target).days)
        if best is None or diff < best[0]:
            best = (diff, v)
    if best is None or best[0] > _YOY_TOLERANCE_DAYS or best[1] == 0:
        return None
    base = best[1]
    # Cruce de cero: el cociente da un número, pero no es una variación interpretable
    # (misma doctrina que ``momentum._percent_change``). Honesto declararlo no computable.
    if (base < 0) != (latest_value < 0):
        return None
    return round((latest_value / base - 1.0) * 100.0, 2)


#: La clasificación vive en el contrato compartido (mismo lugar que FAVORABLE/
#: ADVERSO/NEUTRAL y que la doctrina de umbrales); acá queda su nombre histórico.
_classify = classify_factor


def _factor_from_doctrine(fdoc: dict, grouped: Dict[str, Obs], names: Dict[str, str]) -> MacroFactor:
    impacted = [{"slug": s, "name": names.get(s, s)} for s in fdoc.get("impacted_sectors", [])]
    agents = list(fdoc.get("impacted_agents", []))
    unit = fdoc.get("unit")
    base = dict(
        key=fdoc["key"], label=fdoc["label"], unit=unit,
        impacted_sectors=impacted, impacted_agents=agents,
        series_code=fdoc.get("series_code"), rationale=fdoc.get("rationale", ""),
    )

    obs = grouped.get(fdoc.get("series_code", ""), [])
    clean = [(p, float(v)) for p, v in obs if v is not None]
    if not clean:
        return MacroFactor(value=None, direction=ND, magnitude=ND,
                           reading="sin dato disponible", trend=None, **base)

    mode = fdoc.get("mode", "level")
    trend = compute_series_momentum(clean).get("trend")
    if mode == "change":
        yoy = _yoy_change(clean)
        if yoy is None:
            return MacroFactor(value=None, direction=ND, magnitude=ND,
                               reading="sin variación interanual computable", trend=trend, **base)
        value = yoy
    else:
        value = round(clean[-1][1] * float(fdoc.get("scale", 1.0)), 2)

    reading = factor_reading(value, fdoc)
    direction, magnitude = _classify(value, fdoc)
    return MacroFactor(value=value, direction=direction, magnitude=magnitude,
                       reading=reading, trend=trend, **base)


def build_macro_context(
    db: Session, period: Optional[str] = None, grouped: Optional[Dict[str, Obs]] = None,
) -> MacroSectorContract:
    """Produce the macro→sectorial contract from the latest BCRD series.

    *grouped* (``{series_code: [(period, value)]}``) can be passed to reuse the
    snapshot's already-computed grouping; otherwise it's read here. *period* only
    labels the contract — the factor values always reflect the latest reads.
    """
    doctrine = load_doctrine_raw("macro_sector")
    if grouped is None:
        grouped = _series_by_code(db)
    names = _sector_names()
    factors = [_factor_from_doctrine(f, grouped, names) for f in doctrine.get("factors", [])]
    return MacroSectorContract(
        period=period,
        factors=factors,
        generated_from="macro_monitor",
        doctrine_version=doctrine.get("version"),
    )
