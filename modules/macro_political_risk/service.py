"""Macro-Political Risk — persistence + events service layer.

The scoring engine (`scoring/engine.py`) is deterministic and DB-agnostic.
This service runs it, persists the result as an :class:`IRMPSnapshot` (with its
per-dimension breakdown) and publishes ``irmp.updated`` so other axes
(banking_score outlook, sector_intel acceleration) can react — never by direct
table access.
"""
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.macro_political_risk.events import publish_irmp_updated
from modules.macro_political_risk.models.models import (
    Country,
    CountryVariable,
    DimensionScore,
    IRMPSnapshot,
    RiskBand,
)
from modules.macro_political_risk.scoring.engine import run_irmp

logger = logging.getLogger("sdq.macro_political_risk.service")


def snapshot_breakdown_incomplete(breakdown: Optional[Dict[str, Any]]) -> bool:
    """True si el breakdown dimensional tiene alguna dimensión SIN variables — un IRMP
    inválido (p.ej. computado desde un dataset parcial). Un IRMP legítimo puebla las 5
    dimensiones; una dimensión con 0 variables da score 0 y falsea el índice. Criterio
    único usado por la guarda de persistencia (E2E-F4) y por la op de limpieza."""
    if not breakdown:
        return True
    return any(not (d or {}).get("variables") for d in breakdown.values())


def _get_or_create_country(
    db: Session, iso_code: str, name: Optional[str] = None, region: Optional[str] = None
) -> Country:
    """Upsert a country by ISO code (peer-set registry)."""
    country = db.query(Country).filter_by(iso_code=iso_code).first()
    if country is None:
        country = Country(iso_code=iso_code, name=name or iso_code, region=region)
        db.add(country)
        db.flush()  # assign id without committing
    elif name and country.name == country.iso_code:
        # Backfill a real name if we only had the ISO placeholder.
        country.name = name
    return country


def compute_and_persist(
    db: Session,
    country_code: str,
    dataset: Dict[str, Dict[str, float]],
    period_end: date,
    country_name: Optional[str] = None,
    region: Optional[str] = None,
    publish: bool = True,
) -> Dict[str, Any]:
    """Compute the IRMP for *country_code*, persist it and publish ``irmp.updated``.

    Idempotent per ``(country, period_end)``: re-running replaces the snapshot
    and its dimension rows in place.  Returns the engine result enriched with the
    persisted ``snapshot_id``. ``publish=False`` suprime el evento (para el backfill
    de trayectoria, que persiste cientos de snapshots históricos y no debe disparar
    el recompute de los demás ejes en cada uno).
    """
    result = run_irmp(country_code, dataset)  # raises KeyError if absent

    # E2E-F4: guarda de completitud. Un dataset parcial (p.ej. el smoke E2E con 3 variables)
    # produce un IRMP con dimensiones de 0 variables (score 0) — una lectura inválida que
    # nunca debe persistirse a prod. Un IRMP legítimo puebla las 5 dimensiones.
    if snapshot_breakdown_incomplete(result.get("dimensions")):
        empties = [k for k, d in (result.get("dimensions") or {}).items()
                   if not (d or {}).get("variables")]
        raise ValueError(
            f"Dataset IRMP incompleto para {country_code}: dimensiones sin variables "
            f"({', '.join(empties) or 'todas'}). No se persiste un snapshot parcial."
        )

    country = _get_or_create_country(db, country_code, country_name, region)

    snapshot = (
        db.query(IRMPSnapshot)
        .filter_by(country_id=country.id, period_end=period_end)
        .first()
    )
    if snapshot is None:
        snapshot = IRMPSnapshot(country_id=country.id, period_end=period_end)
        db.add(snapshot)

    snapshot.irmp_score = result["irmp_score"]
    snapshot.risk_band = RiskBand(result["risk_band"])  # value lookup ("Bajo" → bajo)
    snapshot.peer_set_size = result["peer_set_size"]
    snapshot.model_version = result["model_version"]
    snapshot.breakdown = result["dimensions"]

    # Replace per-dimension rows (delete-orphan cascade clears the old ones).
    snapshot.dimension_scores = [
        DimensionScore(
            dimension=dim,
            score=detail["score"],
            weight=detail["weight"],
            contribution=detail["contribution"],
        )
        for dim, detail in result["dimensions"].items()
    ]

    db.commit()
    db.refresh(snapshot)

    payload = {
        "country_code": country_code,
        "country_id": country.id,
        "snapshot_id": snapshot.id,
        "period_end": period_end.isoformat(),
        "irmp_score": result["irmp_score"],
        "risk_band": result["risk_band"],
    }
    if publish:
        publish_irmp_updated(payload)
    logger.info(
        "IRMP persistido y publicado: %s | %s → %s (%s)",
        country_code, period_end, result["irmp_score"], result["risk_band"],
    )

    return {**result, "snapshot_id": snapshot.id, "period_end": period_end.isoformat()}


def delete_invalid_snapshots(db: Session) -> Dict[str, Any]:
    """Borra los IRMPSnapshot con breakdown incompleto (alguna dimensión con 0 variables) —
    lecturas inválidas de datasets parciales (E2E-F4). Reutilizable e idempotente: sin
    snapshots inválidos no borra nada. La cascada delete-orphan limpia las filas de dimensión.
    """
    victims = [s for s in db.query(IRMPSnapshot).all()
               if snapshot_breakdown_incomplete(s.breakdown)]
    removed = [{"country": (s.country.iso_code if s.country else s.country_id),
                "period_end": str(s.period_end), "irmp_score": s.irmp_score}
               for s in victims]
    for s in victims:
        db.delete(s)
    db.commit()
    logger.info("IRMP cleanup: %d snapshots inválidos borrados: %s",
                len(removed), removed)
    return {"deleted": len(removed), "snapshots": removed}


def get_latest(db: Session, country_code: str) -> Optional[IRMPSnapshot]:
    """Most recent persisted snapshot for *country_code* (or None)."""
    return (
        db.query(IRMPSnapshot)
        .join(Country, Country.id == IRMPSnapshot.country_id)
        .filter(Country.iso_code == country_code)
        .order_by(IRMPSnapshot.period_end.desc())
        .first()
    )


def get_country_variables(
    db: Session, period: Optional[str] = None, source: Optional[str] = "WGI"
) -> Dict[str, Any]:
    """Read persisted variables grouped by country: ``{iso: {variable: value}}``.

    *source* filters to one upstream (e.g. ``"WGI"``); pass ``None`` to return
    every source (WGI + WDI + IMF_WEO + declared). When *period* is omitted, uses
    the most recent period present (annual → lexical sort over the 4-digit year).
    Returns the period actually used plus the variable list, so callers can
    overlay live data without fabricating missing values.
    """
    base = db.query(CountryVariable)
    if source is not None:
        base = base.filter(CountryVariable.source == source)

    if period is not None:
        rows = base.filter(CountryVariable.period == period).all()
    else:
        # Latest period PER (country, variable). Sources publish on different
        # lags (WGI vs WDI vs IMF), so a single global "max period" would silently
        # drop a source that trails — take each variable at its own latest instead.
        latest: Dict[tuple, CountryVariable] = {}
        for r in base.all():
            key = (r.iso_code, r.variable)
            cur = latest.get(key)
            if cur is None or r.period > cur.period:
                latest[key] = r
        rows = list(latest.values())

    countries: Dict[str, Dict[str, float]] = {}
    variables = set()
    used_periods = set()
    for r in rows:
        if r.value is None:  # missing stays missing — never overlaid downstream
            continue
        countries.setdefault(r.iso_code, {})[r.variable] = float(r.value)
        variables.add(r.variable)
        used_periods.add(r.period)
    return {
        "source": source or "ALL",
        # Representative period for display (the most recent observed). Individual
        # variables may be at an earlier period; values are each point-in-time.
        "period": (period or (max(used_periods) if used_periods else None)),
        "has_data": bool(countries),
        "countries": countries,
        "variables": sorted(variables),
    }


# electoral_uncertainty = RIESGO DE CALENDARIO: proximidad a la próxima elección general
# (evento electoral en el horizonte → incertidumbre de política/transición). Dato real
# derivado del ``election_calendar`` (fechas verificables), no la rúbrica tecleada. Función
# monótona decreciente en los meses a la próxima elección, con piso (siempre hay algo de
# incertidumbre de base) y horizonte (más allá de ~un ciclo, el timing casi no pesa).
_ELECTORAL_HORIZON_MONTHS = 48
_ELECTORAL_FLOOR = 10.0


def _months_to_next_election(anchor: str, term_years: int, as_of_year: int) -> Optional[int]:
    """Meses desde el cierre de *as_of_year* (31-dic) hasta la próxima elección general
    on/after esa fecha, rodando el ``anchor`` (``"YYYY-MM"``) por ``term_years``.
    ``None`` si el ancla es inválida."""
    try:
        ay, am = (int(x) for x in anchor.split("-"))
    except (ValueError, AttributeError):
        return None
    if not (1 <= am <= 12) or term_years <= 0:
        return None
    as_of_m = as_of_year * 12 + 12  # fin de año del período
    ey = ay
    while ey * 12 + am < as_of_m:
        ey += term_years
    while (ey - term_years) * 12 + am >= as_of_m:
        ey -= term_years
    return ey * 12 + am - as_of_m


def _electoral_uncertainty(months: int) -> float:
    """Meses a la próxima elección → 0-100 (mayor = más incertidumbre). Elección cercana
    → alto; lejana → tiende al piso. Risk-increasing: el motor la invierte."""
    u = 100.0 * (1.0 - months / _ELECTORAL_HORIZON_MONTHS)
    return round(max(_ELECTORAL_FLOOR, min(100.0, u)), 2)


def _electoral_uncertainty_map(as_of_year: Optional[int]) -> Dict[str, float]:
    """``{iso: electoral_uncertainty}`` as-of *as_of_year* desde el calendario electoral
    de la doctrina. ``{}`` si no hay año de referencia."""
    if as_of_year is None:
        return {}
    from shared.doctrine import load_doctrine_raw

    calendar = load_doctrine_raw("regulatory").get("election_calendar", {}) or {}
    out: Dict[str, float] = {}
    for iso, spec in calendar.items():
        months = _months_to_next_election(
            str(spec.get("anchor", "")), int(spec.get("term_years", 0) or 0), as_of_year)
        if months is not None:
            out[iso] = _electoral_uncertainty(months)
    return out


def assemble_irmp_dataset(db: Session, period: Optional[str] = None) -> Dict[str, Any]:
    """Full IRMP dataset per country: declared rubric (doctrine) overlaid with
    persisted live/declared data (real wins). Single source of truth so the
    persisted snapshot and the UI score the same inputs.

    Returns ``{period, dataset: {iso: {var: value}}, sources: {iso: {var:
    "live"|"rubric"}}, has_live}``. The ``sources`` map powers a real-vs-rubric
    disclosure. Rubric values not yet sourced stay declared — never fabricated.

    ``electoral_uncertainty`` is COMPUTED here from the ``election_calendar``
    doctrine as-of the assembled period (proximity to the next general election),
    overriding the declared rubric with a real, auditable signal.
    """
    from shared.doctrine import load_doctrine_raw

    rubric = load_doctrine_raw("regulatory").get("rubric_inputs", {})
    live = get_country_variables(db, period=period, source=None)
    # as-of el año del período (fin de año); si no hay período resuelto, sin overlay.
    as_of_year = None
    if live["period"] and str(live["period"])[:4].isdigit():
        as_of_year = int(str(live["period"])[:4])
    electoral = _electoral_uncertainty_map(as_of_year)
    dataset: Dict[str, Dict[str, float]] = {}
    sources: Dict[str, Dict[str, str]] = {}
    isos = set(rubric) | set(live["countries"])
    for iso in isos:
        merged = {k: float(v) for k, v in (rubric.get(iso) or {}).items()}
        smap = {k: "rubric" for k in merged}
        for var, val in live["countries"].get(iso, {}).items():
            merged[var] = val
            smap[var] = "live"
        # electoral_uncertainty computada (calendario) — dato real, gana sobre la rúbrica.
        if iso in electoral:
            merged["electoral_uncertainty"] = electoral[iso]
            smap["electoral_uncertainty"] = "live"
        dataset[iso] = merged
        sources[iso] = smap
    return {
        "period": live["period"],
        "dataset": dataset,
        "sources": sources,
        "has_live": live["has_data"],
    }


def get_snapshot(
    db: Session, country_code: str, period_end: Optional[date] = None
) -> Optional[IRMPSnapshot]:
    """Snapshot for *country_code* at *period_end*, or the most recent if *period_end*
    is None or has no snapshot (commercial delivery passes the global period; a country
    may lag it). Lets the catalog serve a country's risk read at the chosen period."""
    if period_end is not None:
        hit = (
            db.query(IRMPSnapshot)
            .join(Country, Country.id == IRMPSnapshot.country_id)
            .filter(Country.iso_code == country_code,
                    IRMPSnapshot.period_end == period_end)
            .first()
        )
        if hit is not None:
            return hit
    return get_latest(db, country_code)


def get_panel(db: Session, period_end: date) -> List[IRMPSnapshot]:
    """All persisted snapshots for *period_end*, most resilient first (higher IRMP =
    lower risk). The peer set as actually scored that period — powers a country's
    relative position (rank within the panel) without re-running the engine."""
    return (
        db.query(IRMPSnapshot)
        .filter(IRMPSnapshot.period_end == period_end)
        .order_by(IRMPSnapshot.irmp_score.desc())
        .all()
    )


def get_scored_countries(db: Session) -> List[Country]:
    """Active countries that have at least one persisted IRMP snapshot, by name.

    The catalog offers only countries that actually produce a risk report (the
    banking-scope doctrine: never offer an option that would 422)."""
    return (
        db.query(Country)
        .filter(Country.is_active.is_(True),
                Country.id.in_(db.query(IRMPSnapshot.country_id)))
        .order_by(Country.name)
        .all()
    )


def get_history(db: Session, country_code: str, limit: int = 20) -> List[IRMPSnapshot]:
    """Snapshot history for *country_code*, most recent first."""
    return (
        db.query(IRMPSnapshot)
        .join(Country, Country.id == IRMPSnapshot.country_id)
        .filter(Country.iso_code == country_code)
        .order_by(IRMPSnapshot.period_end.desc())
        .limit(limit)
        .all()
    )


# WGI governance dimensions → Spanish label (report/UI). Order = report order.
GOVERNANCE_DIMENSIONS: Dict[str, str] = {
    "wgi_voice_accountability": "Voz y rendición de cuentas",
    "wgi_political_stability": "Estabilidad política",
    "wgi_gov_effectiveness": "Efectividad gubernamental",
    "wgi_regulatory_quality": "Calidad regulatoria",
    "wgi_rule_of_law": "Estado de derecho",
    "wgi_control_corruption": "Control de la corrupción",
}


def get_governance_profile(
    db: Session, country_code: str, period: Optional[str] = None
) -> Dict[str, Any]:
    """Governance profile for *country_code* from the WGI-2025 store.

    For each of the six governance dimensions returns the latest (or *period*)
    absolute 0-100 score with its confidence interval, source count and 35-source
    breakdown (from ``CountryVariable.meta``), plus the full annual trajectory.
    Reads real data only — a dimension with no persisted rows is simply omitted.
    """
    rows = (
        db.query(CountryVariable)
        .filter(
            CountryVariable.iso_code == country_code,
            CountryVariable.variable.in_(GOVERNANCE_DIMENSIONS.keys()),
            CountryVariable.value.isnot(None),
        )
        .all()
    )
    by_var: Dict[str, List[CountryVariable]] = {}
    for r in rows:
        by_var.setdefault(r.variable, []).append(r)

    dimensions: Dict[str, Any] = {}
    resolved_period: Optional[str] = None
    for var, label in GOVERNANCE_DIMENSIONS.items():
        series = sorted(by_var.get(var, []), key=lambda r: r.period)
        if not series:
            continue
        target = period or series[-1].period
        latest = next((r for r in series if r.period == target), series[-1])
        resolved_period = resolved_period or latest.period
        meta = latest.meta or {}
        dimensions[var] = {
            "label": label,
            "period": latest.period,
            "score": latest.value,
            "ci_lo": meta.get("ci_lo"),
            "ci_hi": meta.get("ci_hi"),
            "n_sources": meta.get("n_sources"),
            "sources": meta.get("sources") or {},
            "trajectory": [
                {"year": r.period, "score": r.value} for r in series
            ],
        }
    return {
        "country_code": country_code,
        "period": resolved_period,
        "dimensions": dimensions,
        "source": "WGI 2025 (World Bank, escala absoluta 0-100)",
    }


# ─── Superficie para la Data API (docs/SPEC_API_DATOS_PROPIETARIOS.md F2) ──


def describe_irmp_for_api(db: Session) -> Dict[str, Any]:
    """Descriptor del IRMP para el manifiesto de la Data API. El módulo describe su
    propio score; la capa API nunca consulta ``mpr_irmp_snapshots`` directamente."""
    countries = get_scored_countries(db)
    latest = (
        db.query(IRMPSnapshot).order_by(IRMPSnapshot.period_end.desc()).first()
    )
    n_obs = db.query(IRMPSnapshot).count()
    periods = sorted({pe.isoformat() for (pe,) in db.query(IRMPSnapshot.period_end).all() if pe})
    return {
        "code": "irmp",
        "label": "Índice de Riesgo Macro-Político (IRMP)",
        "subject_kind": "country",
        "direction": "mayor score = menor riesgo",
        "scale": "0-100",
        "method_version": str(latest.model_version) if latest else None,
        "subjects": tuple(c.iso_code for c in countries),
        "period_latest": latest.period_end.isoformat() if latest else None,
        "periods": tuple(periods),
        "n_obs": int(n_obs),
    }


def irmp_observations_for_api(
    db: Session,
    *,
    subject: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Observaciones del IRMP con desglose dimensional numérico (nunca narrativa).

    Sin ``subject`` devuelve el último snapshot de CADA país (la vista de panel);
    con ``subject`` la trayectoria de ese país. Fechas en ISO (YYYY-MM-DD).
    """
    q = (
        db.query(IRMPSnapshot, Country.iso_code)
        .join(Country, Country.id == IRMPSnapshot.country_id)
    )
    if subject:
        q = q.filter(Country.iso_code == subject.upper())
    if start:
        q = q.filter(IRMPSnapshot.period_end >= start)
    if end:
        q = q.filter(IRMPSnapshot.period_end <= end)
    rows = q.order_by(IRMPSnapshot.period_end.desc()).all()

    pairs: List[Any] = list(rows)
    if not subject:
        # Panel: el snapshot más reciente por país (las filas ya vienen desc).
        seen: set = set()
        latest: List[Any] = []
        for snap, iso in pairs:
            if iso in seen:
                continue
            seen.add(iso)
            latest.append((snap, iso))
        pairs = latest
    if limit is not None and limit > 0:
        pairs = pairs[: int(limit)]

    out: List[Dict[str, Any]] = []
    for snap, iso in pairs:
        dims = {
            d.dimension: {"score": d.score, "weight": d.weight,
                          "contribution": d.contribution}
            for d in snap.dimension_scores
        }
        out.append({
            "subject": iso,
            "period": snap.period_end.isoformat(),
            "score": float(snap.irmp_score),
            "band": snap.risk_band.value if snap.risk_band else None,
            "dimensions": dims or None,
            "model_version": str(snap.model_version) if snap.model_version else None,
        })
    return out
