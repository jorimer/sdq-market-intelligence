"""Energy Intel — IRSE computation, persistence and events.

Reads the SIE open data (installed capacity + claims) via ``sie_client``, computes
the electric-sector resilience index (IRSE) for the latest year and persists it.
The energy transition dimension is a declared gap (no trustworthy CKAN source);
the index reports on capacity + service over real data only.
"""
import logging
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.energy_intel.events import publish_energy_updated
from modules.energy_intel.models.models import EnergyScore
from modules.energy_intel.scoring.resilience import compute_energy_index

logger = logging.getLogger("sdq.energy_intel.service")

MODEL_VERSION = "1.1"  # 1.1: dimensión de transición (penetración renovable, ONE)


def assemble_energy_dataset(
    capacity_by_year: Optional[Dict[int, float]] = None,
    claims: Optional[List[Dict[str, Any]]] = None,
    renewable_share_by_year: Optional[Dict[int, float]] = None,
) -> Dict[str, Any]:
    """Fetch SIE capacity + claims and ONE renewable penetration (live) unless
    provided, and compute the IRSE.

    Returns ``{period, index}`` where ``period`` is the latest capacity year. Raises
    if there is no capacity data (caller treats the sync as best-effort). The
    generation/transition fetch is best-effort: a failure leaves transition as a gap
    rather than tumbling the whole sync. Fully-provided inputs (tests) never hit the
    network — the live fetch only runs when an input is missing."""
    capacity_by_year, claims, renewable_share_by_year = _fetch_inputs(
        capacity_by_year, claims, renewable_share_by_year)
    index = compute_energy_index(capacity_by_year, claims, renewable_share_by_year)
    period = str(max(capacity_by_year))
    return {"period": period, "index": index}


def _fetch_inputs(
    capacity_by_year: Optional[Dict[int, float]],
    claims: Optional[List[Dict[str, Any]]],
    renewable_share_by_year: Optional[Dict[int, float]],
):
    """Insumos del IRSE: los provistos (tests) o el fetch live (SIE + ONE best-effort)."""
    live = capacity_by_year is None or claims is None
    if live:
        from shared.data.sie_client import sie_client
        capacity_by_year = capacity_by_year or sie_client.installed_capacity()
        claims = claims if claims is not None else sie_client.claims()
    if renewable_share_by_year is None and live:
        try:
            from shared.data.generation_client import generation_client
            renewable_share_by_year = generation_client.renewable_penetration()
        except Exception as e:  # noqa: BLE001 — transición best-effort, no tumbar el sync
            logger.warning("penetración renovable (ONE) no disponible: %s", e)
            renewable_share_by_year = None
    if not capacity_by_year:
        raise ValueError("SIE no devolvió capacidad instalada.")
    return capacity_by_year, claims, renewable_share_by_year


def _write_score(db: Session, period: str, index: Dict[str, Any]) -> EnergyScore:
    """Upsert del ``EnergyScore`` de *period* (no commitea — el llamador decide)."""
    row = db.query(EnergyScore).filter_by(period=period).first()
    if row is None:
        row = EnergyScore(period=period)
        db.add(row)
    row.energy_score = index["energy_score"]
    row.band = index["band"]
    row.coverage = index["coverage"]
    row.capacity_mw = (index["capacity"] or {}).get("capacity_mw")
    row.capacity_score = (index["capacity"] or {}).get("score")
    row.service_score = (index["service"] or {}).get("score")
    row.transition_score = (index["transition"] or {}).get("score")
    row.breakdown = {"dimensions": index["dimensions"], "capacity": index["capacity"],
                     "service": index["service"], "transition": index["transition"]}
    row.model_version = MODEL_VERSION
    return row


def compute_and_persist(
    db: Session,
    capacity_by_year: Optional[Dict[int, float]] = None,
    claims: Optional[List[Dict[str, Any]]] = None,
    renewable_share_by_year: Optional[Dict[int, float]] = None,
) -> Dict[str, Any]:
    """Compute the IRSE for the latest year, persist it and publish ``energy.updated``.

    Idempotent per period: re-running replaces the score in place."""
    asm = assemble_energy_dataset(capacity_by_year, claims, renewable_share_by_year)
    period, index = asm["period"], asm["index"]

    row = _write_score(db, period, index)
    db.commit()
    db.refresh(row)
    payload = {"period": period, "energy_score": index["energy_score"], "band": index["band"]}
    publish_energy_updated(payload)
    logger.info("IRSE %s: score=%s (%s), coverage=%s",
                period, index["energy_score"], index["band"], index["coverage"])
    return {"period": period, "score_id": row.id, **payload, "coverage": index["coverage"],
            "model_version": MODEL_VERSION}


def backfill_scores(
    db: Session,
    capacity_by_year: Optional[Dict[int, float]] = None,
    claims: Optional[List[Dict[str, Any]]] = None,
    renewable_share_by_year: Optional[Dict[int, float]] = None,
) -> Dict[str, Any]:
    """Compute & persist el IRSE para cada año con cobertura PLENA (3/3 dimensiones).

    Antes solo se persistía el año más reciente → el selector de períodos del producto
    ofrecía 1 opción pese a que las fuentes traen historia (capacidad SIE desde 1998,
    reclamaciones desde 2019, renovables desde 2001). Misma doctrina de comparabilidad
    que construcción (``construction_intel.service.backfill_scores``): solo se persisten
    los años donde las TRES dimensiones son medibles — mezclar años de 2 dimensiones con
    años de 3 daría una serie incomparable que lee como salto falso del índice. En la
    práctica la serie plena arranca ~2020 (cuando las reclamaciones acumulan su ventana
    de 12 meses). Cada año se computa AS-OF: insumos truncados a esa fecha. Publica el
    evento UNA vez (con el último año). Idempotente: upsert por período."""
    capacity_by_year, claims, renewable_share_by_year = _fetch_inputs(
        capacity_by_year, claims, renewable_share_by_year)

    persisted: List[str] = []
    last: Optional[Dict[str, Any]] = None
    for y in sorted(capacity_by_year):
        cap_y = {k: v for k, v in capacity_by_year.items() if k <= y}
        claims_y = [r for r in (claims or []) if str(r.get("period") or "") <= f"{y}-12"]
        ren_y = ({k: v for k, v in renewable_share_by_year.items() if k <= y}
                 if renewable_share_by_year else None)
        index = compute_energy_index(cap_y, claims_y, ren_y)
        if index["energy_score"] is None or (index["coverage"] or 0.0) < 0.999:
            continue
        _write_score(db, str(y), index)
        persisted.append(str(y))
        last = {"period": str(y), "energy_score": index["energy_score"],
                "band": index["band"], "coverage": index["coverage"]}
    if last is None:
        # Sin ningún año de cobertura plena: cae al comportamiento anterior (el más
        # reciente, con su cobertura declarada) — el producto nunca queda sin score.
        return compute_and_persist(db, capacity_by_year, claims, renewable_share_by_year)

    db.commit()
    publish_energy_updated({"period": last["period"], "energy_score": last["energy_score"],
                            "band": last["band"]})
    logger.info("IRSE backfill: %d años persistidos (%s → %s)",
                len(persisted), persisted[0], persisted[-1])
    return {**last, "periods": persisted, "model_version": MODEL_VERSION}


def get_latest(db: Session, period: Optional[str] = None) -> Optional[EnergyScore]:
    q = db.query(EnergyScore)
    if period:
        return q.filter_by(period=period).first()
    return q.order_by(EnergyScore.period.desc()).first()


def get_scores(db: Session) -> List[EnergyScore]:
    return db.query(EnergyScore).order_by(EnergyScore.period.desc()).all()
