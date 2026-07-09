"""Servicio de transacciones facturables (monetización Fase 4).

Registra cada cobro confirmado con su desglose fiscal (subtotal + impuesto = total) y le
asigna un correlativo de factura interno. Lo llama el webhook al confirmar el pago; es
idempotente por ``(provider, event_id)`` (el mismo evento no duplica el cobro), en línea con
la deduplicación de ``BillingEvent``.

``invoice_number`` es un correlativo interno legible (``SDQ-{año}-{NNNNN}``), NO un NCF de la
DGII: la secuencia de comprobante fiscal es un dato que el dueño debe cargar (brecha legal).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.billing.models import BillingTransaction
from shared.billing.tax import TaxBreakdown

logger = logging.getLogger("sdq.billing.transactions")

_INVOICE_PREFIX = "SDQ"


def intended_encf_type(breakdown: TaxBreakdown, *, client_has_rnc: bool = False) -> str:
    """Tipo de e-CF (DGII) previsto para una transacción, según la matriz fiscal RD:
    exportación de servicios (cliente del exterior, exento) → **46**; cliente local con RNC
    que necesita crédito fiscal → **31**; consumidor final local → **32** (default). El e-NCF
    real lo asigna la integración con la DGII (secuencia autorizada + firma digital)."""
    if breakdown.exempt:
        return "46"
    return "31" if client_has_rnc else "32"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _next_invoice_number(db: Session, *, year: int) -> str:
    """Correlativo ``SDQ-{año}-{NNNNN}`` global por año. El unique index del número actúa de
    red de seguridad ante carreras (el caller reintenta ante IntegrityError)."""
    prefix = f"{_INVOICE_PREFIX}-{year}-"
    count = (db.query(func.count(BillingTransaction.id))
             .filter(BillingTransaction.invoice_number.like(f"{prefix}%"))
             .scalar()) or 0
    return f"{prefix}{count + 1:05d}"


def _serialize(t: BillingTransaction) -> Dict[str, Any]:
    return {
        "id": t.id,
        "user_id": t.user_id,
        "sku": t.sku,
        "kind": t.kind,
        "provider": t.provider,
        "provider_ref": t.provider_ref,
        "currency": t.currency,
        "subtotal": format(t.subtotal, "f") if t.subtotal is not None else None,
        "tax_rate": format(t.tax_rate, "f") if t.tax_rate is not None else None,
        "tax_amount": format(t.tax_amount, "f") if t.tax_amount is not None else None,
        "total": format(t.total, "f") if t.total is not None else None,
        "tax_label": t.tax_label,
        "tax_exempt": bool(t.tax_exempt),
        "country": t.country,
        "invoice_number": t.invoice_number,
        "status": t.status,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "encf_type": t.encf_type,
        "encf_number": t.encf_number,
        "encf_status": t.encf_status,
    }


def record_transaction_once(db: Session, *, user_id: str, sku: str, kind: str, provider: str,
                            provider_ref: Optional[str], event_id: Optional[str],
                            breakdown: TaxBreakdown, note: Optional[str] = None) -> tuple:
    """Registra un cobro facturable con su desglose y devuelve ``(dict, created)``. Idempotente
    por ``(provider, event_id)``: si ya existe una transacción para ese evento, la devuelve con
    ``created=False`` (sin crear otra). El ``event_id`` determinista por ``provider_ref`` hace
    que el webhook y el retorno/captura converjan en UNA sola factura (lo enforca el índice
    único). ``created`` permite conceder el acceso exactamente una vez."""
    if event_id:
        existing = (db.query(BillingTransaction)
                    .filter_by(provider=provider, event_id=event_id).one_or_none())
        if existing is not None:
            return _serialize(existing), False

    now = _utcnow()
    for attempt in range(4):  # reintentos ante colisión del correlativo (carrera)
        invoice_number = _next_invoice_number(db, year=now.year)
        row = BillingTransaction(
            user_id=user_id, sku=sku, kind=kind, provider=provider,
            provider_ref=provider_ref, event_id=event_id,
            currency=breakdown.currency,
            subtotal=Decimal(breakdown.subtotal),
            tax_rate=Decimal(breakdown.rate_pct or "0"),
            tax_amount=Decimal(breakdown.tax),
            total=Decimal(breakdown.total),
            tax_label=breakdown.label,
            tax_exempt=bool(breakdown.exempt),
            country=breakdown.country,
            invoice_number=invoice_number,
            status="paid", note=note,
            encf_type=intended_encf_type(breakdown), encf_status="pending")
        db.add(row)
        try:
            db.commit()
            return _serialize(row), True
        except IntegrityError:
            db.rollback()
            # Otra entrega concurrente ganó por (provider, event_id) o por el correlativo.
            if event_id:
                existing = (db.query(BillingTransaction)
                            .filter_by(provider=provider, event_id=event_id).one_or_none())
                if existing is not None:
                    return _serialize(existing), False
            if attempt == 3:
                raise
    raise RuntimeError("No se pudo asignar un número de factura.")  # pragma: no cover


def record_transaction(db: Session, **kwargs) -> Dict[str, Any]:
    """Como ``record_transaction_once`` pero devuelve solo el dict (back-compat)."""
    return record_transaction_once(db, **kwargs)[0]


def list_user_transactions(db: Session, user_id: str) -> List[Dict[str, Any]]:
    """Facturas del usuario, más recientes primero."""
    rows = (db.query(BillingTransaction)
            .filter_by(user_id=user_id)
            .order_by(BillingTransaction.created_at.desc())
            .all())
    return [_serialize(r) for r in rows]


def get_user_transaction(db: Session, *, user_id: str,
                         transaction_id: str) -> Optional[BillingTransaction]:
    """Una transacción del usuario por id (scope al dueño — no filtra facturas ajenas)."""
    return (db.query(BillingTransaction)
            .filter_by(id=transaction_id, user_id=user_id).one_or_none())
