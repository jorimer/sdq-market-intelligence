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
from typing import Any, cast, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.billing.fiscal.types import REGIME_ECF, REGIME_NCF, doc_label
from shared.billing.models import BillingTransaction
from shared.billing.tax import TaxBreakdown

logger = logging.getLogger("sdq.billing.transactions")

_INVOICE_PREFIX = "SDQ"


def intended_doc_type(breakdown: TaxBreakdown, *, regime: str,
                      client_has_rnc: bool = False) -> str:
    """Tipo de comprobante que corresponde a una venta, según la matriz fiscal RD, expresado
    en los códigos del RÉGIMEN pedido:

    - exportación de servicios (cliente del exterior, exento) → NCF **16** / e-CF **46**
    - cliente local que aporta su RNC y necesita crédito fiscal → NCF **01** / e-CF **31**
    - consumidor final local (default conservador) → NCF **02** / e-CF **32**

    La matriz se escribe UNA vez, en códigos de NCF, y se traduce al régimen destino: así el
    cambio de llave a e-CF no la reescribe (y no puede divergir entre los dos motores)."""
    from shared.billing.fiscal.types import (
        NCF_CONSUMO,
        NCF_CREDITO_FISCAL,
        NCF_EXPORTACIONES,
        NCF_TO_ECF,
        REGIME_ECF,
    )

    if breakdown.exempt:
        ncf_type = NCF_EXPORTACIONES
    else:
        ncf_type = NCF_CREDITO_FISCAL if client_has_rnc else NCF_CONSUMO
    return NCF_TO_ECF[ncf_type] if regime == REGIME_ECF else ncf_type


def intended_encf_type(breakdown: TaxBreakdown, *, client_has_rnc: bool = False) -> str:
    """Tipo de e-CF previsto (31/32/46). Atajo sobre ``intended_doc_type`` para el régimen
    electrónico; lo consume el ensamblador de e-CF y se persiste desde el primer día para que
    la transición no tenga que recalcularlo sobre el histórico."""
    from shared.billing.fiscal.types import REGIME_ECF

    return intended_doc_type(breakdown, regime=REGIME_ECF, client_has_rnc=client_has_rnc)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def next_invoice_number(db: Session, *, year: int) -> str:
    """Correlativo ``SDQ-{año}-{NNNNN}`` global por año. El unique index del número actúa de
    red de seguridad ante carreras (el caller reintenta ante IntegrityError). Público porque
    la nota de crédito también es un documento numerado (``fiscal/credit_notes.py``)."""
    prefix = f"{_INVOICE_PREFIX}-{year}-"
    count = (db.query(func.count(BillingTransaction.id))
             .filter(BillingTransaction.invoice_number.like(f"{prefix}%"))
             .scalar()) or 0
    return f"{prefix}{count + 1:05d}"


_next_invoice_number = next_invoice_number  # alias interno (uso histórico)


def _assign_fiscal_number(db: Session, *, breakdown: TaxBreakdown,
                          client_has_rnc: bool) -> Dict[str, Any]:
    """Consume un correlativo de la secuencia autorizada del régimen ACTIVO, **sin commitear**
    (queda en la transacción que crea la factura: si la factura falla, el número no se quema).

    Quedarse sin secuencia NO tumba la venta: devuelve el tipo que correspondía y
    ``status='sin_secuencia'`` con el número en ``None`` — la brecha se declara, no se rellena,
    y la factura sale como comprobante interno hasta que se cargue el rango."""
    from shared.billing.fiscal.sequences import try_allocate
    from shared.billing.fiscal.types import REGIME_NCF
    from shared.settings.service import get_fiscal_regime

    try:
        regime = get_fiscal_regime(db)
    except Exception:  # noqa: BLE001 — tabla de settings ausente (pre-migración/tests)
        db.rollback()
        regime = REGIME_NCF
    doc_type = intended_doc_type(breakdown, regime=regime, client_has_rnc=client_has_rnc)
    allocated = try_allocate(db, regime=regime, doc_type=doc_type, commit=False)
    return {
        "regime": regime,
        "doc_type": doc_type,
        "number": allocated["number"] if allocated else None,
        "expires_at": allocated["expires_at"] if allocated else None,
        "remaining": allocated["remaining"] if allocated else None,
        "status": "emitido" if allocated else "sin_secuencia",
    }


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
        # El número fiscal NUNCA viaja solo: sale con su tipo, su etiqueta y su régimen, o la
        # lectura de al lado lo reatribuye (un "02" es Consumo bajo NCF y nada bajo e-CF).
        "fiscal_regime": REGIME_NCF if t.ncf_number else (REGIME_ECF if t.encf_number else None),
        "fiscal_number": t.ncf_number or t.encf_number,
        "fiscal_doc_type": t.ncf_type if t.ncf_number else (t.encf_type if t.encf_number else None),
        "fiscal_doc_label": (doc_label(REGIME_NCF, str(t.ncf_type or "")) if t.ncf_number else
                             (doc_label(REGIME_ECF, str(t.encf_type or "")) if t.encf_number
                              else None)),
        "ncf_type": t.ncf_type,
        "ncf_number": t.ncf_number,
        "ncf_status": t.ncf_status,
        "ncf_valid_until": t.ncf_valid_until.isoformat() if t.ncf_valid_until else None,
        "encf_type": t.encf_type,
        "encf_number": t.encf_number,
        "encf_status": t.encf_status,
    }


def record_transaction_once(db: Session, *, user_id: str, sku: str, kind: str, provider: str,
                            provider_ref: Optional[str], event_id: Optional[str],
                            breakdown: TaxBreakdown, note: Optional[str] = None,
                            encf_type: Optional[str] = None,
                            client_has_rnc: bool = False) -> tuple:
    """Registra un cobro facturable con su desglose y devuelve ``(dict, created)``. Idempotente
    por ``(provider, event_id)``: si ya existe una transacción para ese evento, la devuelve con
    ``created=False`` (sin crear otra). El ``event_id`` determinista por ``provider_ref`` hace
    que el webhook y el retorno/captura converjan en UNA sola factura (lo enforca el índice
    único). ``created`` permite conceder el acceso exactamente una vez.

    El **comprobante fiscal se asigna acá, en el mismo commit**: el correlativo se consume y la
    factura se persiste juntos, o ninguno de los dos. Un reintento por colisión de correlativo
    revierte también el avance de la secuencia, así que no deja huecos sin explicación."""
    if event_id:
        existing = (db.query(BillingTransaction)
                    .filter_by(provider=provider, event_id=event_id).one_or_none())
        if existing is not None:
            return _serialize(existing), False

    now = _utcnow()
    for attempt in range(4):  # reintentos ante colisión del correlativo (carrera)
        fiscal = _assign_fiscal_number(db, breakdown=breakdown, client_has_rnc=client_has_rnc)
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
            encf_type=encf_type or intended_encf_type(breakdown, client_has_rnc=client_has_rnc),
            encf_status="pending")
        if fiscal["regime"] == REGIME_NCF:
            row.ncf_type = fiscal["doc_type"]
            row.ncf_number = fiscal["number"]
            row.ncf_status = fiscal["status"]
            row.ncf_valid_until = cast(Any, fiscal["expires_at"])
            row.ncf_issued_at = cast(Any, now if fiscal["number"] else None)
        db.add(row)
        try:
            db.commit()
            _warn_if_sequence_running_out(db, fiscal)
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


def _warn_if_sequence_running_out(db: Session, fiscal: Dict[str, Any]) -> None:
    """Publica el aviso de secuencia al borde (o ya agotada) DESPUÉS de commitear la factura.
    Avisar nunca debe tumbar un cobro ya registrado."""
    from shared.billing.events import FISCAL_SEQUENCE_LOW
    from shared.billing.fiscal.sequences import LOW_REMAINING
    from shared.events.event_bus import event_bus

    remaining = fiscal.get("remaining")
    exhausted = fiscal["number"] is None
    if not exhausted and not (remaining is not None and remaining < LOW_REMAINING):
        return
    try:
        event_bus.publish(FISCAL_SEQUENCE_LOW, {
            "regime": fiscal["regime"], "doc_type": fiscal["doc_type"],
            "remaining": remaining, "exhausted": exhausted,
        })
    except Exception:  # noqa: BLE001 — el aviso no revierte la factura ya persistida
        logger.exception("[fiscal] no se pudo publicar el aviso de secuencia")


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
