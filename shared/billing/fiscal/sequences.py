"""Asignación de secuencias de comprobante fiscal (DGII) — NCF y e-NCF, un solo asignador.

La DGII autoriza un RANGO por (régimen, tipo) con vencimiento; ``allocate_next`` toma el
próximo correlativo controlando vencimiento y agotamiento. Dos propiedades que la versión
anterior no tenía y que son la razón de este módulo:

1. **El avance es un compare-and-swap**, no un ``row.current += 1``. El
   ``SELECT … FOR UPDATE`` sirve en Postgres pero SQLite lo ignora en silencio: dos
   asignaciones concurrentes leían el MISMO ``current`` y emitían el MISMO número. El
   ``UPDATE … WHERE current = :leído`` verificando ``rowcount == 1`` es correcto en las dos
   bases, sin depender del bloqueo. (El ``FOR UPDATE`` se conserva en Postgres para que la
   segunda espere en vez de reintentar.)
2. **No commitea por su cuenta** cuando lo llama la facturación (``commit=False``): el
   correlativo se consume en la MISMA transacción que crea la ``BillingTransaction``. Si la
   factura falla, el avance se revierte con ella y el número no queda quemado sin comprobante
   que lo explique.

El agotamiento **no puede tumbar una venta**: quien factura llama a ``try_allocate``, que
devuelve ``None`` en vez de lanzar, registra el cobro con ``ncf_status='sin_secuencia'`` y
declara la brecha. Cerrarla es cargar el rango y asignar retroactivamente.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from shared.billing.fiscal.types import (
    FiscalTypeError,
    format_number,
    spec_for,
    validate_type,
)
from shared.billing.models import FiscalSequence

logger = logging.getLogger("sdq.billing.fiscal")

# Reintentos del compare-and-swap ante contención (otra asignación ganó la carrera).
_MAX_ATTEMPTS = 5

# Umbrales del aviso preventivo: se avisa ANTES de quedarse sin números, no al fallar.
LOW_REMAINING = 20        # quedan menos de N correlativos
EXPIRING_DAYS = 30        # o vence dentro de N días


class FiscalSequenceError(RuntimeError):
    """No hay secuencia disponible (no configurada, vencida o agotada)."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    """UTC-naive (la comparación de vencimiento se hace contra un naive del lado SQL)."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _usable(db: Session, regime: str, doc_type: str, *, now: datetime, lock: bool):
    """Fila ACTIVA, no vencida y con cupo del (régimen, tipo), la de rango más bajo."""
    q = (db.query(FiscalSequence)
         .filter(FiscalSequence.regime == regime,
                 FiscalSequence.doc_type == doc_type,
                 FiscalSequence.active.is_(True),
                 FiscalSequence.current <= FiscalSequence.range_to,
                 or_(FiscalSequence.expires_at.is_(None), FiscalSequence.expires_at > now))
         .order_by(FiscalSequence.range_from.asc()))
    if lock and db.bind is not None and db.bind.dialect.name != "sqlite":
        # Postgres: la segunda asignación espera a que la primera commitee y re-evalúa la
        # fila ya avanzada. SQLite no soporta FOR UPDATE — ahí protege el compare-and-swap.
        q = q.with_for_update()
    return q.first()


def _claim(db: Session, row: FiscalSequence, expected: int) -> bool:
    """Compare-and-swap: avanza ``current`` sólo si sigue valiendo ``expected`` y hay cupo.
    Devuelve si este llamador se quedó con el correlativo. No commitea."""
    updated = (db.query(FiscalSequence)
               .filter(FiscalSequence.id == row.id,
                       FiscalSequence.current == Decimal(expected),
                       FiscalSequence.current <= FiscalSequence.range_to)
               .update({FiscalSequence.current: Decimal(expected + 1)},
                       synchronize_session=False))
    return updated == 1


def allocate_next(db: Session, *, regime: str, doc_type: str,
                  commit: bool = True) -> Dict[str, Any]:
    """Asigna el próximo comprobante del (régimen, tipo). Devuelve
    ``{number, regime, doc_type, sequence_number, expires_at, remaining}``.

    ``commit=False`` deja el avance en la transacción abierta del llamador (lo usa la
    facturación, para que el número y la factura vivan o mueran juntos).
    Lanza ``FiscalSequenceError`` si no hay rango disponible."""
    doc_type = validate_type(regime, doc_type)
    spec = spec_for(regime)
    now = _utcnow()

    for _ in range(_MAX_ATTEMPTS):
        row = _usable(db, spec.regime, doc_type, now=now, lock=True)
        if row is None:
            raise FiscalSequenceError(
                f"No hay secuencia disponible para el tipo {doc_type} de {spec.label} "
                "(no configurada, vencida o agotada). Cargue el rango autorizado por la DGII.")
        expected = int(row.current)
        if _claim(db, row, expected):
            expires_at = row.expires_at
            remaining = int(row.range_to) - expected
            if commit:
                db.commit()
            return {
                "number": format_number(spec.regime, doc_type, expected),
                "regime": spec.regime,
                "doc_type": doc_type,
                "sequence_number": expected,
                "expires_at": expires_at,
                "remaining": max(0, remaining),
            }
        # Otra asignación se quedó con ese correlativo: releer y reintentar.
        db.expire(row)

    raise FiscalSequenceError(
        f"No se pudo asignar un comprobante del tipo {doc_type} por contención. Reintente.")


def try_allocate(db: Session, *, regime: str, doc_type: str,
                 commit: bool = False) -> Optional[Dict[str, Any]]:
    """Como ``allocate_next`` pero devuelve ``None`` en vez de lanzar cuando no hay secuencia.
    Es la puerta que usa la FACTURACIÓN: quedarse sin números no puede tumbar un cobro ya
    hecho — se registra el cobro con la brecha declarada y se avisa al admin."""
    try:
        return allocate_next(db, regime=regime, doc_type=doc_type, commit=commit)
    except (FiscalSequenceError, FiscalTypeError) as e:
        logger.warning("[fiscal] sin secuencia para %s/%s: %s", regime, doc_type, e)
        return None


# ── Consulta y administración de rangos ──────────────────────────────

def _serialize(s: FiscalSequence, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or _utcnow()
    remaining = int(s.range_to) - int(s.current) + 1
    expired = bool(s.expires_at and s.expires_at <= now)
    exhausted = remaining <= 0
    total = int(s.range_to) - int(s.range_from) + 1
    regime, doc_type = str(s.regime), str(s.doc_type)
    try:
        label = spec_for(regime).labels.get(doc_type, "Comprobante fiscal")
        next_number = (format_number(regime, doc_type, int(s.current))
                       if remaining > 0 else None)
    except FiscalTypeError:  # fila con un tipo que ya no es válido para su régimen
        label, next_number = "Comprobante fiscal", None
    return {
        "id": s.id,
        "regime": regime,
        "doc_type": doc_type,
        "doc_label": label,
        "range_from": str(int(s.range_from)),
        "range_to": str(int(s.range_to)),
        "current": str(int(s.current)),
        "issued": max(0, total - max(0, remaining)),
        "total": total,
        "remaining": max(0, remaining),
        "expires_at": s.expires_at.isoformat() if s.expires_at else None,
        "active": bool(s.active),
        "expired": expired,
        "exhausted": exhausted,
        "usable": bool(s.active) and not expired and not exhausted,
        "low": bool(s.active) and not expired and 0 < remaining < LOW_REMAINING,
        "expiring_soon": bool(s.expires_at and not expired
                              and s.expires_at <= now + timedelta(days=EXPIRING_DAYS)),
        "note": s.note,
        "next_number": next_number,
    }


def list_sequences(db: Session, *, regime: Optional[str] = None) -> List[Dict[str, Any]]:
    """Rangos cargados, ordenados por régimen/tipo. Filtra por régimen si se da."""
    now = _utcnow()
    q = db.query(FiscalSequence)
    if regime:
        q = q.filter(FiscalSequence.regime == regime)
    rows = q.order_by(FiscalSequence.regime, FiscalSequence.doc_type,
                      FiscalSequence.range_from).all()
    return [_serialize(r, now=now) for r in rows]


def upsert_sequence(db: Session, *, regime: str, doc_type: str, range_from: int, range_to: int,
                    current: Optional[int] = None, expires_at: Optional[datetime] = None,
                    active: bool = True, note: Optional[str] = None) -> Dict[str, Any]:
    """Alta o actualización del rango de un (régimen, tipo). Una fila activa por combinación:
    si ya existe una activa, se actualiza. ``current`` None = arranca en ``range_from``."""
    doc_type = validate_type(regime, doc_type)
    spec = spec_for(regime)
    lo, hi = int(range_from), int(range_to)
    if hi < lo:
        raise FiscalSequenceError("El fin del rango debe ser ≥ el inicio.")
    if lo < 1 or hi > spec.max_sequence:
        raise FiscalSequenceError(
            f"El rango debe estar entre 1 y {spec.max_sequence} para {spec.label} "
            f"({spec.seq_digits} dígitos de secuencia).")
    start = int(current) if current is not None else lo
    if start < lo or start > hi + 1:
        raise FiscalSequenceError("El correlativo actual está fuera del rango.")

    row = (db.query(FiscalSequence)
           .filter_by(regime=spec.regime, doc_type=doc_type, active=True)
           .order_by(FiscalSequence.range_from.desc()).first())
    if row is None:
        row = FiscalSequence(regime=spec.regime, doc_type=doc_type)
        db.add(row)
    # cast: SQLAlchemy tipa las columnas como Column[...]; los valores son Decimal/datetime/bool.
    row.range_from = cast(Any, Decimal(lo))
    row.range_to = cast(Any, Decimal(hi))
    row.current = cast(Any, Decimal(start))
    row.expires_at = cast(Any, _naive(expires_at))
    row.active = cast(Any, active)
    if note is not None:
        row.note = cast(Any, note)
    db.commit()
    return _serialize(row)


def sequences_needing_attention(db: Session) -> List[Dict[str, Any]]:
    """Rangos activos que se están por agotar o por vencer — lo que hay que avisar ANTES de
    que falle un cobro. Vacío si todo está holgado."""
    return [s for s in list_sequences(db)
            if s["active"] and (s["low"] or s["expiring_soon"] or s["exhausted"]
                                or s["expired"])]
