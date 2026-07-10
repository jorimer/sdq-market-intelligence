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
) -> Dict[str, Any]:
    """Compute the IRMP for *country_code*, persist it and publish ``irmp.updated``.

    Idempotent per ``(country, period_end)``: re-running replaces the snapshot
    and its dimension rows in place.  Returns the engine result enriched with the
    persisted ``snapshot_id``.
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


def assemble_irmp_dataset(db: Session, period: Optional[str] = None) -> Dict[str, Any]:
    """Full IRMP dataset per country: declared rubric (doctrine) overlaid with
    persisted live/declared data (real wins). Single source of truth so the
    persisted snapshot and the UI score the same inputs.

    Returns ``{period, dataset: {iso: {var: value}}, sources: {iso: {var:
    "live"|"rubric"}}, has_live}``. The ``sources`` map powers a real-vs-rubric
    disclosure. Rubric values not yet sourced stay declared — never fabricated.
    """
    from shared.doctrine import load_doctrine_raw

    rubric = load_doctrine_raw("regulatory").get("rubric_inputs", {})
    live = get_country_variables(db, period=period, source=None)
    dataset: Dict[str, Dict[str, float]] = {}
    sources: Dict[str, Dict[str, str]] = {}
    isos = set(rubric) | set(live["countries"])
    for iso in isos:
        merged = {k: float(v) for k, v in (rubric.get(iso) or {}).items()}
        smap = {k: "rubric" for k in merged}
        for var, val in live["countries"].get(iso, {}).items():
            merged[var] = val
            smap[var] = "live"
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
