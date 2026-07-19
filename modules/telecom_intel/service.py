"""Telecom Intel — IDT computation, persistence and events.

Reads INDOTEL's quarterly bulletin via ``indotel_client``, computes the telecom
development index (IDT) for the latest published quarter and persists it.
"""
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.telecom_intel.events import publish_telecom_updated
from modules.telecom_intel.models.models import TelecomScore
from modules.telecom_intel.scoring.penetration import (
    compute_telecom_index,
    compute_telecom_index_itu,
)

logger = logging.getLogger("sdq.telecom_intel.service")

MODEL_VERSION = "1.0"


def assemble_telecom_dataset_itu(
    indicators: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Trae las penetraciones telecom de RD de ITU DataHub (live) y computa el IDT.

    Fuente VIGENTE (INDOTEL congelado en 2022-Q1). ``{period, index}``; levanta si ITU
    no devolvió penetración (best-effort)."""
    if indicators is None:
        from shared.data.itu_client import itu_client
        indicators = itu_client.fetch_indicators()
    period = indicators.get("period") or "—"
    keys = ("mobile_penetration", "mobile_broadband_penetration", "fixed_broadband_penetration")
    if not any(indicators.get(k) is not None for k in keys):
        raise ValueError("ITU no devolvió penetración de telecom.")
    index = compute_telecom_index_itu(
        indicators.get("mobile_penetration"),
        indicators.get("mobile_broadband_penetration"),
        indicators.get("fixed_broadband_penetration"),
        indicators.get("households_internet"))
    return {"period": period, "index": index}


def assemble_telecom_dataset(
    indicators: Optional[Dict[str, Any]] = None,
    population: Optional[int] = None,
) -> Dict[str, Any]:
    """Fetch INDOTEL indicators (live) unless provided, and compute the IDT.

    Returns ``{period, index}``. Raises if no indicators (caller best-effort)."""
    from shared.data.indotel_client import POP_2022

    period = "—"
    if indicators is None:
        from shared.data.indotel_client import indotel_client
        fetched = indotel_client.fetch_indicators()
        period = fetched.pop("period", "—")
        indicators = fetched
    else:
        period = indicators.pop("period", "—") if "period" in indicators else "—"
    if not any(indicators.get(k) is not None
               for k in ("lines_total", "internet_total", "broadband_total")):
        raise ValueError("INDOTEL no devolvió indicadores de telecom.")
    index = compute_telecom_index(indicators, population or POP_2022)
    return {"period": period, "index": index}


def _write_score(db: Session, per: str, index: Dict[str, Any]) -> TelecomScore:
    """Upsert del ``TelecomScore`` de *per* (no commitea — el llamador decide)."""
    row = db.query(TelecomScore).filter_by(period=per).first()
    if row is None:
        row = TelecomScore(period=per)
        db.add(row)
    m = index["metrics"]
    row.telecom_score = index["telecom_score"]
    row.band = index["band"]
    row.coverage = index["coverage"]
    row.mobile_penetration = m.get("mobile_penetration")
    row.internet_penetration = m.get("internet_penetration")
    row.broadband_share = m.get("broadband_share")
    row.breakdown = {"dimensions": index["dimensions"], "metrics": m}
    row.model_version = MODEL_VERSION
    return row


def _persist_index(db: Session, per: str, index: Dict[str, Any]) -> Dict[str, Any]:
    """Persiste un IDT computado (común a INDOTEL e ITU) + publica ``telecom.updated``."""
    row = _write_score(db, per, index)
    db.commit()
    db.refresh(row)
    payload = {"period": per, "telecom_score": index["telecom_score"], "band": index["band"]}
    publish_telecom_updated(payload)
    logger.info("IDT %s: score=%s (%s), coverage=%s",
                per, index["telecom_score"], index["band"], index["coverage"])
    return {"period": per, "score_id": row.id, **payload, "coverage": index["coverage"],
            "model_version": MODEL_VERSION}


def compute_and_persist(
    db: Session,
    indicators: Optional[Dict[str, Any]] = None,
    population: Optional[int] = None,
    period: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute the IDT (INDOTEL), persist it and publish ``telecom.updated``."""
    asm = assemble_telecom_dataset(indicators, population)
    return _persist_index(db, period or asm["period"], asm["index"])


def compute_and_persist_itu(
    db: Session,
    indicators: Optional[Dict[str, Any]] = None,
    period: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute the IDT desde ITU DataHub (fuente vigente), persist + publish."""
    asm = assemble_telecom_dataset_itu(indicators)
    return _persist_index(db, period or asm["period"], asm["index"])


def backfill_scores_itu(
    db: Session,
    by_code: Optional[Dict[int, Dict[int, float]]] = None,
) -> Dict[str, Any]:
    """Compute & persist el IDT para cada AÑO con cobertura PLENA (3/3 pilares) desde ITU.

    Antes solo se persistía el año más reciente → el selector de períodos del producto
    ofrecía 1 opción real (más un artefacto INDOTEL congelado), pese a que ITU trae
    historia anual larga (móvil desde 2000, banda ancha móvil desde 2007, fija desde
    2003). Misma doctrina de comparabilidad que energía/construcción: solo se persisten
    los años con los TRES pilares medibles (mezclar años de 2 y 3 pilares leería como
    salto falso del índice) → serie comparable ~2007 en adelante. Cada año usa SU dato
    (exact-year, sin arrastrar el futuro). Publica el evento UNA vez (último año).
    Idempotente: upsert por período.

    ITU es la serie CANÓNICA de telecom (anual, fuente vigente). Al establecerla, se
    retiran los puntos trimestrales heredados de INDOTEL (fuente muerta, congelada en
    2022-Q1): tienen otra metodología (conteos absolutos vs. penetración per-100) y
    sandwicheados entre los años ITU leen como una serie incomparable. ITU cubre esa
    historia y más (anual desde 2000), así que el retiro es estrictamente una mejora."""
    from shared.data.itu_client import itu_client, parse_indicators_for_year
    if by_code is None:
        by_code = itu_client.fetch_by_code()
    years = sorted({y for series in by_code.values() for y in series})

    persisted: List[str] = []
    last: Optional[Dict[str, Any]] = None
    for y in years:
        ind = parse_indicators_for_year(by_code, y)
        index = compute_telecom_index_itu(
            ind["mobile_penetration"], ind["mobile_broadband_penetration"],
            ind["fixed_broadband_penetration"], ind["households_internet"])
        if index["telecom_score"] is None or (index["coverage"] or 0.0) < 0.999:
            continue
        _write_score(db, str(y), index)
        persisted.append(str(y))
        last = {"period": str(y), "telecom_score": index["telecom_score"],
                "band": index["band"], "coverage": index["coverage"]}
    if last is None:
        # Sin ningún año pleno: cae a la vista live (último año, cobertura declarada).
        return compute_and_persist_itu(db)

    pruned = _prune_legacy_quarterly(db)
    db.commit()
    publish_telecom_updated({"period": last["period"],
                             "telecom_score": last["telecom_score"], "band": last["band"]})
    logger.info("IDT backfill ITU: %d años (%s → %s); %d trimestres INDOTEL retirados",
                len(persisted), persisted[0], persisted[-1], pruned)
    return {**last, "periods": persisted, "pruned_legacy": pruned,
            "model_version": MODEL_VERSION}


_QUARTERLY_PERIOD = re.compile(r"^\d{4}-Q[1-4]$")


def _prune_legacy_quarterly(db: Session) -> int:
    """Retira los ``TelecomScore`` de período trimestral (``YYYY-Qn``, artefactos INDOTEL)
    para dejar SOLO la serie anual canónica de ITU. Devuelve cuántos borró. No commitea —
    el llamador (backfill) hace un único commit con la serie nueva + este retiro."""
    stale = [s for s in db.query(TelecomScore).all()
             if _QUARTERLY_PERIOD.match(str(s.period or ""))]
    for row in stale:
        db.delete(row)
    return len(stale)


def get_latest(db: Session, period: Optional[str] = None) -> Optional[TelecomScore]:
    q = db.query(TelecomScore)
    if period:
        return q.filter_by(period=period).first()
    return q.order_by(TelecomScore.period.desc()).first()


def get_scores(db: Session) -> List[TelecomScore]:
    return db.query(TelecomScore).order_by(TelecomScore.period.desc()).all()
