"""Free Zones Intel — IZF computation, persistence and events.

Reads the CNZFE open data (free-zone sector fundamentals) via ``cnzfe_client``,
computes the attractiveness index (IZF) for the latest year and persists it.
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.free_zones_intel.events import publish_free_zones_updated
from modules.free_zones_intel.models.models import FreeZoneScore
from modules.free_zones_intel.scoring.attractiveness import compute_free_zone_index

logger = logging.getLogger("sdq.free_zones_intel.service")

MODEL_VERSION = "1.0"


def assemble_free_zone_dataset(
    vars_by_year: Optional[Dict[int, Dict[str, float]]] = None,
) -> Dict[str, Any]:
    """Fetch CNZFE fundamentals (live) unless provided, and compute the IZF.

    Returns ``{period, index}`` where ``period`` is the latest year. Raises if there is
    no data (caller treats the sync as best-effort). Fully-provided inputs (tests) never
    hit the network."""
    if vars_by_year is None:
        from shared.data.cnzfe_client import cnzfe_client
        vars_by_year = cnzfe_client.free_zone_vars()
    if not vars_by_year:
        raise ValueError("CNZFE no devolvió variables del sector.")
    index = compute_free_zone_index(vars_by_year)
    period = str(max(vars_by_year))
    return {"period": period, "index": index}


def _write_score(db: Session, period: str, index: Dict[str, Any]) -> FreeZoneScore:
    """Upsert (sin commit) la fila IZF de un período. Reusado por compute y backfill."""
    row = db.query(FreeZoneScore).filter_by(period=period).first()
    if row is None:
        row = FreeZoneScore(period=period)
        db.add(row)
    levels = index["levels"] or {}
    row.fz_score = index["fz_score"]
    row.band = index["band"]
    row.coverage = index["coverage"]
    row.exports_musd = levels.get("exports_musd")
    row.investment_musd = levels.get("investment_musd")
    row.jobs = levels.get("jobs")
    row.companies = levels.get("companies")
    row.breakdown = {"dimensions": index["dimensions"], "exports": index["exports"],
                     "investment": index["investment"], "employment": index["employment"],
                     "productivity": index["productivity"], "levels": levels}
    row.model_version = MODEL_VERSION
    return row


def compute_and_persist(
    db: Session,
    vars_by_year: Optional[Dict[int, Dict[str, float]]] = None,
) -> Dict[str, Any]:
    """Compute the IZF for the latest year, persist it and publish ``free_zones.updated``.

    Idempotent per period: re-running replaces the score in place."""
    asm = assemble_free_zone_dataset(vars_by_year)
    period, index = asm["period"], asm["index"]

    row = _write_score(db, period, index)
    db.commit()
    db.refresh(row)
    payload = {"period": period, "fz_score": index["fz_score"], "band": index["band"]}
    publish_free_zones_updated(payload)
    logger.info("IZF %s: score=%s (%s), coverage=%s",
                period, index["fz_score"], index["band"], index["coverage"])
    return {"period": period, "score_id": row.id, **payload, "coverage": index["coverage"],
            "model_version": MODEL_VERSION}


def backfill_scores(
    db: Session,
    vars_by_year: Optional[Dict[int, Dict[str, float]]] = None,
) -> Dict[str, Any]:
    """Compute & persist the IZF for EVERY computable year (the index *as of* each year).

    Para cada año Y se computa el IZF sobre el subconjunto de variables ≤Y (igual que lo
    haría la sync en ese año); el CAGR a 3 años usa Y-3..Y de ese subconjunto. Los años sin
    base suficiente (score None) se omiten — no se persiste una fila vacía. Publica el evento
    UNA vez (con el último año). Idempotente: upsert por período."""
    if vars_by_year is None:
        from shared.data.cnzfe_client import cnzfe_client
        vars_by_year = cnzfe_client.free_zone_vars()
    if not vars_by_year:
        raise ValueError("CNZFE no devolvió variables del sector.")

    persisted: List[str] = []
    last: Optional[Dict[str, Any]] = None
    for y in sorted(vars_by_year):
        subset = {yy: v for yy, v in vars_by_year.items() if yy <= y}
        index = compute_free_zone_index(subset)
        if index["fz_score"] is None:  # sin base de CAGR aún → no se persiste fila vacía
            continue
        _write_score(db, str(y), index)
        persisted.append(str(y))
        last = {"period": str(y), "fz_score": index["fz_score"], "band": index["band"]}
    db.commit()
    if last:
        publish_free_zones_updated(last)
    logger.info("IZF backfill: %d años persistidos (%s..%s)",
                len(persisted), persisted[0] if persisted else "—",
                persisted[-1] if persisted else "—")
    return {"persisted_periods": persisted, "latest": persisted[-1] if persisted else None,
            "count": len(persisted), "model_version": MODEL_VERSION}


def get_latest(db: Session, period: Optional[str] = None) -> Optional[FreeZoneScore]:
    q = db.query(FreeZoneScore)
    if period:
        return q.filter_by(period=period).first()
    return q.order_by(FreeZoneScore.period.desc()).first()


def get_scores(db: Session) -> List[FreeZoneScore]:
    return db.query(FreeZoneScore).order_by(FreeZoneScore.period.desc()).all()
