"""Construction Intel — ICC computation, persistence and events.

Reads MIVHED open data (building-permit activity) via ``mivhed_client`` and the BCRD's
construction-sector real growth via ``shared.data.bcrd_sectors``, computes the construction
index (ICC) for the latest COMPLETE year and persists it. A partial current year (a quarter
of permits, not a full year) is dropped — never annualized.
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.construction_intel.events import publish_construction_updated
from modules.construction_intel.models.models import ConstructionScore
from modules.construction_intel.scoring.momentum import compute_construction_index

logger = logging.getLogger("sdq.construction_intel.service")

MODEL_VERSION = "1.0"

_MONTHS_FULL_YEAR = 12  # un año "completo" del MIVHED tiene los 12 meses


def _bcrd_construction_growth() -> Dict[int, float]:
    """``{year: real_growth_pct}`` del PIB de construcción (BCRD cuentas nacionales)."""
    from shared.data.bcrd_sectors import VAR_GROWTH, bcrd_sectors_client
    out: Dict[int, float] = {}
    for r in bcrd_sectors_client.fetch(series=VAR_GROWTH):
        if getattr(r, "dimension", None) == "construccion" and r.value is not None:
            try:
                out[int(r.period)] = float(r.value)
            except (ValueError, TypeError):
                continue
    return out


def _complete_years(licenses_by_year: Dict[int, Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """Solo los años con los 12 meses presentes (descarta un año en curso parcial)."""
    return {y: r for y, r in licenses_by_year.items()
            if r.get("months", 0) >= _MONTHS_FULL_YEAR}


def _fetch_one_typology() -> Optional[Dict[str, Any]]:
    """Detalle por tipología de la ONE (valor tasado + construcciones + licencias + m²) del
    último año disponible, o ``None`` si la ONE no está accesible. Defensivo: la ONE es una
    capa autoritativa COMPLEMENTARIA — si falla, el ICC (sobre MIVHED+BCRD) no se cae."""
    try:
        from shared.data.one_construction import one_construction_client
        return one_construction_client.latest_typology()
    except Exception as e:  # noqa: BLE001
        logger.warning("ONE construcción no disponible (se omite la capa de valor tasado): %s", e)
        return None


def assemble_construction_dataset(
    licenses_by_year: Optional[Dict[int, Dict[str, Any]]] = None,
    growth_by_year: Optional[Dict[int, float]] = None,
    one_typology: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fetch MIVHED permits + BCRD construction growth (live) unless provided, and compute
    the ICC for the latest complete year. Raises if there is no complete year. Fully-provided
    inputs (tests) never hit the network.

    En modo live (sin ``licenses_by_year``) también trae la capa autoritativa de la ONE (valor
    tasado por tipología) y la adjunta al índice; los tests inyectan ``one_typology`` si la
    quieren ejercitar (o lo dejan en ``None``)."""
    live = licenses_by_year is None
    if licenses_by_year is None:
        from shared.data.mivhed_client import mivhed_client
        licenses_by_year = mivhed_client.licenses()
    if growth_by_year is None:
        growth_by_year = _bcrd_construction_growth()
    if one_typology is None and live:
        one_typology = _fetch_one_typology()
    complete = _complete_years(licenses_by_year)
    if not complete:
        raise ValueError("MIVHED no devolvió ningún año completo de licencias.")
    period = max(complete)
    index = compute_construction_index(complete, growth_by_year, period=period)
    if one_typology:
        index["one_typology"] = one_typology
    return {"period": str(period), "index": index}


def _write_score(db: Session, period: str, index: Dict[str, Any]) -> ConstructionScore:
    """Upsert (sin commit) la fila ICC de un período. Reusado por compute y backfill."""
    row = db.query(ConstructionScore).filter_by(period=period).first()
    if row is None:
        row = ConstructionScore(period=period)
        db.add(row)
    levels = index["levels"] or {}
    row.icc_score = index["icc_score"]
    row.band = index["band"]
    row.coverage = index["coverage"]
    row.permits = levels.get("permits")
    row.sqm = levels.get("sqm")
    row.investment_dop = levels.get("investment_dop")
    row.prod_growth_3y = levels.get("prod_growth_3y")
    row.breakdown = {"dimensions": index["dimensions"], "production": index["production"],
                     "pipeline": index["pipeline"], "typology": index["typology"],
                     "geography": index["geography"], "levels": levels,
                     "one_typology": index.get("one_typology")}
    row.model_version = MODEL_VERSION
    return row


def compute_and_persist(
    db: Session,
    licenses_by_year: Optional[Dict[int, Dict[str, Any]]] = None,
    growth_by_year: Optional[Dict[int, float]] = None,
    one_typology: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute the ICC for the latest complete year, persist it and publish
    ``construction.updated``. Idempotent per period: re-running replaces the score in place."""
    asm = assemble_construction_dataset(licenses_by_year, growth_by_year, one_typology)
    period, index = asm["period"], asm["index"]

    row = _write_score(db, period, index)
    db.commit()
    db.refresh(row)
    payload = {"period": period, "icc_score": index["icc_score"], "band": index["band"]}
    publish_construction_updated(payload)
    logger.info("ICC %s: score=%s (%s), coverage=%s",
                period, index["icc_score"], index["band"], index["coverage"])
    return {"period": period, "score_id": row.id, **payload, "coverage": index["coverage"],
            "model_version": MODEL_VERSION}


def backfill_scores(
    db: Session,
    licenses_by_year: Optional[Dict[int, Dict[str, Any]]] = None,
    growth_by_year: Optional[Dict[int, float]] = None,
    one_typology: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute & persist the ICC for every COMPLETE, FULL-COVERAGE year.

    Solo se persisten los años con las 4 dimensiones medibles (cobertura plena). El pipeline
    (CAGR de m²) solo acredita su peso desde que hay ≥4 años de MIVHED (desde 2022), así que
    los años previos quedarían sin esa dimensión: persistirlos sería un ÍNDICE INCOMPARABLE
    (una serie 'sin la señal de pipeline' junto a otra 'con ella' lee como un falso colapso —
    la palanca fácil-pero-incorrecta). Mejor un punto honesto hoy; la serie crece sola a
    medida que el MIVHED acumula años. Publica el evento UNA vez (con el último año).
    Idempotente: upsert por período."""
    live = licenses_by_year is None
    if licenses_by_year is None:
        from shared.data.mivhed_client import mivhed_client
        licenses_by_year = mivhed_client.licenses()
    if growth_by_year is None:
        growth_by_year = _bcrd_construction_growth()
    if one_typology is None and live:
        one_typology = _fetch_one_typology()
    complete = _complete_years(licenses_by_year)
    if not complete:
        raise ValueError("MIVHED no devolvió ningún año completo de licencias.")

    persisted: List[str] = []
    last: Optional[Dict[str, Any]] = None
    for y in sorted(complete):
        index = compute_construction_index(complete, growth_by_year, period=y)
        # cobertura plena: las 4 dimensiones medibles (índice comparable año a año)
        if index["icc_score"] is None or (index["coverage"] or 0.0) < 0.999:
            continue
        # La capa ONE (valor tasado por tipología) se adjunta SOLO al año que coincide con el
        # año de la ONE — nunca se estampa un valor tasado de otro año en un período ajeno.
        if one_typology and str(one_typology.get("year")) == str(y):
            index["one_typology"] = one_typology
        _write_score(db, str(y), index)
        persisted.append(str(y))
        last = {"period": str(y), "icc_score": index["icc_score"], "band": index["band"]}
    db.commit()
    if last:
        publish_construction_updated(last)
    logger.info("ICC backfill: %d años persistidos (%s..%s)",
                len(persisted), persisted[0] if persisted else "—",
                persisted[-1] if persisted else "—")
    return {"persisted_periods": persisted, "latest": persisted[-1] if persisted else None,
            "count": len(persisted), "model_version": MODEL_VERSION}


def get_latest(db: Session, period: Optional[str] = None) -> Optional[ConstructionScore]:
    q = db.query(ConstructionScore)
    if period:
        return q.filter_by(period=period).first()
    return q.order_by(ConstructionScore.period.desc()).first()


def get_scores(db: Session) -> List[ConstructionScore]:
    return db.query(ConstructionScore).order_by(ConstructionScore.period.desc()).all()
