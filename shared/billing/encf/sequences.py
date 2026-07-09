"""Asignación de secuencias e-NCF autorizadas por la DGII (e-CF Slice 2).

El e-NCF tiene el formato ``E`` + tipo (2 díg.) + secuencia (10 díg.) = 13 caracteres. La DGII
autoriza un RANGO por tipo con vencimiento; ``allocate_next`` toma el próximo correlativo,
controlando vencimiento y agotamiento, y avanza el contador de forma atómica (row lock en
Postgres; SQLite serializa las escrituras). El emisor de e-CF (slice posterior) llama a esto
justo antes de armar y firmar el XML.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from shared.billing.encf.types import ECF_CONSUMO, ECF_CREDITO_FISCAL, ECF_EXPORTACION
from shared.billing.models import EncfSequence

VALID_TYPES = {ECF_CREDITO_FISCAL, ECF_CONSUMO, ECF_EXPORTACION}
_SEQ_DIGITS = 10


class EncfSequenceError(RuntimeError):
    """No hay secuencia e-NCF disponible (no configurada, vencida o agotada)."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def format_encf(ecf_type: str, number: int) -> str:
    """``E`` + tipo(2) + secuencia(10) → 13 caracteres. Ej.: (31, 1) → 'E310000000001'."""
    return f"E{ecf_type}{int(number):0{_SEQ_DIGITS}d}"


def _usable(db: Session, ecf_type: str, *, now: datetime, lock: bool):
    q = (db.query(EncfSequence)
         .filter(EncfSequence.ecf_type == ecf_type,
                 EncfSequence.active.is_(True),
                 EncfSequence.current <= EncfSequence.range_to,
                 or_(EncfSequence.expires_at.is_(None), EncfSequence.expires_at > now))
         .order_by(EncfSequence.range_from.asc()))
    if lock:
        try:
            q = q.with_for_update()
        except Exception:  # noqa: BLE001 — SQLite no soporta FOR UPDATE; serializa igual
            pass
    return q.first()


def allocate_next(db: Session, ecf_type: str) -> Dict[str, Any]:
    """Asigna el próximo e-NCF del tipo dado. Devuelve ``{encf, ecf_type, expires_at}``. Lanza
    ``EncfSequenceError`` si no hay rango disponible."""
    if ecf_type not in VALID_TYPES:
        raise EncfSequenceError(f"Tipo de e-CF inválido para secuencia: '{ecf_type}'.")
    now = _utcnow()
    row = _usable(db, ecf_type, now=now, lock=True)
    if row is None:
        raise EncfSequenceError(
            f"No hay secuencia e-NCF disponible para el tipo {ecf_type} "
            "(no configurada, vencida o agotada). Cargue el rango autorizado por la DGII.")
    number = int(row.current)
    row.current = Decimal(number + 1)
    db.commit()
    return {"encf": format_encf(ecf_type, number), "ecf_type": ecf_type,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None}


def _serialize(s: EncfSequence, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or _utcnow()
    remaining = int(s.range_to) - int(s.current) + 1
    expired = bool(s.expires_at and s.expires_at <= now)
    return {
        "id": s.id, "ecf_type": s.ecf_type,
        "range_from": str(int(s.range_from)), "range_to": str(int(s.range_to)),
        "current": str(int(s.current)),
        "remaining": max(0, remaining),
        "expires_at": s.expires_at.isoformat() if s.expires_at else None,
        "active": bool(s.active), "expired": expired,
        "exhausted": remaining <= 0, "note": s.note,
        "next_encf": format_encf(s.ecf_type, int(s.current)) if remaining > 0 else None,
    }


def list_sequences(db: Session) -> List[Dict[str, Any]]:
    now = _utcnow()
    rows = db.query(EncfSequence).order_by(EncfSequence.ecf_type, EncfSequence.range_from).all()
    return [_serialize(r, now=now) for r in rows]


def upsert_sequence(db: Session, *, ecf_type: str, range_from: int, range_to: int,
                    current: Optional[int] = None, expires_at: Optional[datetime] = None,
                    active: bool = True, note: Optional[str] = None) -> Dict[str, Any]:
    """Alta o actualización del rango de secuencia de un tipo. Una fila activa por tipo (si ya
    existe una activa para el tipo, se actualiza). ``current`` None = arranca en ``range_from``."""
    if ecf_type not in VALID_TYPES:
        raise EncfSequenceError(f"Tipo de e-CF inválido: '{ecf_type}'.")
    if int(range_to) < int(range_from):
        raise EncfSequenceError("El fin del rango debe ser ≥ el inicio.")
    start = int(current) if current is not None else int(range_from)
    if start < int(range_from) or start > int(range_to) + 1:
        raise EncfSequenceError("El correlativo actual está fuera del rango.")
    exp = expires_at.astimezone(timezone.utc).replace(tzinfo=None) if (
        expires_at and expires_at.tzinfo) else expires_at

    row = (db.query(EncfSequence)
           .filter_by(ecf_type=ecf_type, active=True)
           .order_by(EncfSequence.range_from.desc()).first())
    if row is None:
        row = EncfSequence(ecf_type=ecf_type, range_from=Decimal(int(range_from)),
                           range_to=Decimal(int(range_to)), current=Decimal(start),
                           expires_at=exp, active=active, note=note)
        db.add(row)
    else:
        row.range_from = Decimal(int(range_from))
        row.range_to = Decimal(int(range_to))
        row.current = Decimal(start)
        row.expires_at = exp
        row.active = active
        if note is not None:
            row.note = note
    db.commit()
    return _serialize(row)
