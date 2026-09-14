"""Tourism Intel — ITT computation, persistence and events.

Reads the ONE open data (non-resident air arrivals) via ``tourism_arrivals_client``,
computes the traction index (ITT) for the latest year and persists it.
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.tourism_intel.events import publish_tourism_updated
from modules.tourism_intel.models.models import TourismScore
from modules.tourism_intel.scoring.traction import compute_tourism_index

logger = logging.getLogger("sdq.tourism_intel.service")

MODEL_VERSION = "1.0"


def assemble_tourism_dataset(
    arrivals_by_year: Optional[Dict[int, Dict[str, object]]] = None,
) -> Dict[str, Any]:
    """Fetch arrivals (live) unless provided, and compute the ITT.

    Returns ``{period, index}`` where ``period`` is the latest year. Raises if there is
    no data (caller treats the sync as best-effort). Fully-provided inputs (tests) never
    hit the network."""
    if arrivals_by_year is None:
        from shared.data.tourism_arrivals_client import tourism_arrivals_client
        arrivals_by_year = tourism_arrivals_client.arrivals()
    if not arrivals_by_year:
        raise ValueError("ONE no devolvió llegadas de turismo.")
    index = compute_tourism_index(arrivals_by_year)
    period = str(max(arrivals_by_year))
    return {"period": period, "index": index}


def _write_score(db: Session, period: str, index: Dict[str, Any]) -> TourismScore:
    """Upsert (sin commit) la fila ITT de un período. Reusado por compute y backfill."""
    row = db.query(TourismScore).filter_by(period=period).first()
    if row is None:
        row = TourismScore(period=period)
        db.add(row)
    levels = index["levels"] or {}
    row.itt_score = index["itt_score"]
    row.band = index["band"]
    row.coverage = index["coverage"]
    row.nonresident = levels.get("nonresident")
    row.foreign = levels.get("foreign")
    row.breakdown = {"dimensions": index["dimensions"], "total_demand": index["total_demand"],
                     "foreign_demand": index["foreign_demand"], "recovery": index["recovery"],
                     "diversification": index["diversification"], "levels": levels}
    row.model_version = MODEL_VERSION
    return row


def compute_and_persist(
    db: Session,
    arrivals_by_year: Optional[Dict[int, Dict[str, object]]] = None,
) -> Dict[str, Any]:
    """Compute the ITT for the latest year, persist it and publish ``tourism.updated``.

    Idempotent per period: re-running replaces the score in place."""
    asm = assemble_tourism_dataset(arrivals_by_year)
    period, index = asm["period"], asm["index"]

    row = _write_score(db, period, index)
    db.commit()
    db.refresh(row)
    payload = {"period": period, "itt_score": index["itt_score"], "band": index["band"]}
    publish_tourism_updated(payload)
    logger.info("ITT %s: score=%s (%s), coverage=%s",
                period, index["itt_score"], index["band"], index["coverage"])
    return {"period": period, "score_id": row.id, **payload, "coverage": index["coverage"],
            "model_version": MODEL_VERSION}


def backfill_scores(
    db: Session,
    arrivals_by_year: Optional[Dict[int, Dict[str, object]]] = None,
) -> Dict[str, Any]:
    """Compute & persist the ITT for EVERY computable year (the index *as of* each year).

    Para cada año Y se computa el ITT sobre el subconjunto de llegadas ≤Y; el CAGR a 3 años
    usa Y-3..Y. Los años sin base suficiente (score None) se omiten. Publica el evento UNA
    vez (con el último año). Idempotente: upsert por período."""
    if arrivals_by_year is None:
        from shared.data.tourism_arrivals_client import tourism_arrivals_client
        arrivals_by_year = tourism_arrivals_client.arrivals()
    if not arrivals_by_year:
        raise ValueError("ONE no devolvió llegadas de turismo.")

    persisted: List[str] = []
    last: Optional[Dict[str, Any]] = None
    for y in sorted(arrivals_by_year):
        subset = {yy: v for yy, v in arrivals_by_year.items() if yy <= y}
        index = compute_tourism_index(subset)
        # Exige la dimensión NÚCLEO (demanda total, CAGR 3y): sin ella el ITT se apoyaría
        # solo en recuperación-vs-sí-mismo + diversificación → score alto engañoso en años
        # tempranos. Persistimos solo desde que hay señal real de tracción de demanda.
        if index["total_demand"]["score"] is None:
            continue
        _write_score(db, str(y), index)
        persisted.append(str(y))
        last = {"period": str(y), "itt_score": index["itt_score"], "band": index["band"]}
    db.commit()
    if last:
        publish_tourism_updated(last)
    logger.info("ITT backfill: %d años persistidos (%s..%s)",
                len(persisted), persisted[0] if persisted else "—",
                persisted[-1] if persisted else "—")
    return {"persisted_periods": persisted, "latest": persisted[-1] if persisted else None,
            "count": len(persisted), "model_version": MODEL_VERSION}


# ── Feed mensual (Fase 6): la llegada de no residentes del BCRD ─────────────────────────

#: El eje en `sector_observations`. Es la misma clave que el producto (`SECTOR_KEY`).
SECTOR_KEY_OBS = "tourism"


def escribir_observaciones_llegadas(db: Session, records, *, publicada, source: str,
                                    license: str) -> int:
    """Las llegadas mensuales en `sector_observations`. No commitea.

    Idempotente como el IMTE y el MIVHED: la hoja del BCRD trae la serie ENTERA desde 1978 en
    cada descarga, así que se borra cada serie y se reescribe. `published_at` es cuándo subió el
    BCRD el archivo a su CDN (`Last-Modified`), no cuándo lo bajamos nosotros.
    """
    from shared.data.series_nature import infer_nature
    from shared.observations import service as obs

    for codigo in sorted({r.series for r in records}):
        obs.borrar_serie(db, sector_key=SECTOR_KEY_OBS, series_code=codigo)
    puntos = {(r.series, r.period): r for r in records}
    for (codigo, periodo), r in sorted(puntos.items()):
        obs.upsert(db, sector_key=SECTOR_KEY_OBS, series_code=codigo, period=periodo,
                   value=r.value, unit=r.unit, frequency="monthly",
                   nature=infer_nature(r.unit, code=codigo), source=source,
                   license=license, published_at=publicada)
    return len(puntos)


def sincronizar_llegadas_mensuales(db: Session, client: Any = None) -> Dict[str, Any]:
    """Baja la hoja de no residentes del BCRD y la persiste. Commitea. Lanza si la fuente
    falla: decide el llamador, que no deja que el feed tumbe el índice."""
    from shared.data.bcrd_llegadas_client import BCRDLlegadasClient

    client = client or BCRDLlegadasClient(mode="live")
    registros, edicion = client.leer_ultima_edicion()
    n = escribir_observaciones_llegadas(db, registros, publicada=edicion.publicada,
                                        source=client.source, license=client.license)
    db.commit()
    return {"periodo": edicion.periodo, "publicada": (edicion.publicada.isoformat()
                                                      if edicion.publicada else None),
            "puntos": n, "modo": client.mode}


def get_latest(db: Session, period: Optional[str] = None) -> Optional[TourismScore]:
    q = db.query(TourismScore)
    if period:
        return q.filter_by(period=period).first()
    return q.order_by(TourismScore.period.desc()).first()


def get_scores(db: Session) -> List[TourismScore]:
    return db.query(TourismScore).order_by(TourismScore.period.desc()).all()
