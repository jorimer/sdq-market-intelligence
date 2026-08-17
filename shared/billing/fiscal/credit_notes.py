"""Notas de crédito (NCF tipo 04 / e-CF 34) — el comprobante que revierte una factura.

Un reembolso no se documenta borrando ni editando la factura original: el comprobante emitido
existe y ya se reportó. Se emite un comprobante NUEVO —la nota de crédito— que la modifica y
que en el Formato 607 declara, en su columna «Número Comprobante Fiscal Modificado», cuál
factura revierte.

Por eso la nota de crédito es una fila propia en ``billing_transaction`` (``kind='credit_note'``)
con su propio correlativo de la secuencia 04, y no un estado de la original. La original queda
como estaba, marcada ``status='refunded'``, y las dos se reportan.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, cast

from sqlalchemy.orm import Session

from shared.billing.fiscal.types import (
    NCF_NOTA_CREDITO,
    NCF_TO_ECF,
    REGIME_NCF,
    doc_label,
)
from shared.billing.models import BillingTransaction

logger = logging.getLogger("sdq.billing.fiscal.credit_notes")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _amounts_for(tx: BillingTransaction, gross: Optional[str]) -> Dict[str, Decimal]:
    """Montos de la nota. Un reembolso TOTAL revierte el desglose original tal cual; uno
    PARCIAL se prorratea sobre el bruto devuelto, manteniendo la misma tasa.

    Los montos se guardan en POSITIVO: la nota de crédito es un documento de signo propio, no
    un importe negativo (así lo declara el 607 y así lo lee un contador)."""
    total_original = Decimal(str(tx.total or "0"))
    if gross is None or total_original == 0:
        return {"subtotal": Decimal(str(tx.subtotal or "0")),
                "tax": Decimal(str(tx.tax_amount or "0")),
                "total": total_original}
    try:
        devuelto = Decimal(str(gross))
    except Exception:  # noqa: BLE001 — bruto ilegible → se revierte todo
        return {"subtotal": Decimal(str(tx.subtotal or "0")),
                "tax": Decimal(str(tx.tax_amount or "0")),
                "total": total_original}
    if devuelto >= total_original:
        return {"subtotal": Decimal(str(tx.subtotal or "0")),
                "tax": Decimal(str(tx.tax_amount or "0")),
                "total": total_original}
    proporcion = devuelto / total_original
    cents = Decimal("0.01")
    subtotal = (Decimal(str(tx.subtotal or "0")) * proporcion).quantize(cents)
    tax = (devuelto - subtotal).quantize(cents)
    return {"subtotal": subtotal, "tax": tax, "total": devuelto.quantize(cents)}


def issue_credit_note(db: Session, tx: BillingTransaction, *, refund_ref: str,
                      gross: Optional[str] = None,
                      currency: Optional[str] = None) -> Dict[str, Any]:
    """Emite la nota de crédito de una factura reembolsada y devuelve su resumen.

    Consume un correlativo de la secuencia de notas de crédito. Si esa secuencia no está
    cargada, la nota se registra IGUAL sin número (``sin_secuencia``) — el reembolso ya
    ocurrió y negarse a registrarlo dejaría el reembolso sin rastro contable. Aparece entre
    los pendientes de numerar, como cualquier otra brecha declarada."""
    from shared.billing.fiscal.sequences import try_allocate
    from shared.billing.transactions import next_invoice_number
    from shared.settings.service import get_fiscal_regime

    existing = (db.query(BillingTransaction)
                .filter_by(kind="credit_note", credits_transaction_id=tx.id)
                .one_or_none())
    if existing is not None:
        return _serialize(existing)

    try:
        regime = get_fiscal_regime(db)
    except Exception:  # noqa: BLE001 — settings ausente (pre-migración/tests)
        db.rollback()
        regime = REGIME_NCF
    doc_type = (NCF_NOTA_CREDITO if regime == REGIME_NCF
                else NCF_TO_ECF[NCF_NOTA_CREDITO])
    montos = _amounts_for(tx, gross)
    now = _utcnow()

    allocated = try_allocate(db, regime=regime, doc_type=doc_type, commit=False)
    nota = BillingTransaction(
        user_id=tx.user_id, sku=tx.sku, kind="credit_note", provider=tx.provider,
        provider_ref=refund_ref, event_id=f"refund:{refund_ref}",
        currency=currency or tx.currency,
        subtotal=montos["subtotal"], tax_rate=tx.tax_rate, tax_amount=montos["tax"],
        total=montos["total"], tax_label=tx.tax_label, tax_exempt=tx.tax_exempt,
        country=tx.country, invoice_number=next_invoice_number(db, year=now.year),
        status="issued", note=f"Nota de crédito de {tx.invoice_number or tx.id}",
        credits_transaction_id=tx.id)
    if regime == REGIME_NCF:
        nota.ncf_type = cast(Any, doc_type)
        nota.ncf_number = cast(Any, allocated["number"] if allocated else None)
        nota.ncf_status = cast(Any, "emitido" if allocated else "sin_secuencia")
        nota.ncf_valid_until = cast(Any, allocated["expires_at"] if allocated else None)
        nota.ncf_issued_at = cast(Any, now if allocated else None)
    else:
        nota.encf_type = cast(Any, doc_type)
        nota.encf_number = cast(Any, allocated["number"] if allocated else None)
        nota.encf_status = cast(Any, "issued" if allocated else "pending")
    db.add(nota)
    db.commit()

    logger.info("[fiscal] nota de crédito %s emitida sobre %s (%s %s)",
                nota.ncf_number or nota.encf_number or "SIN NÚMERO",
                tx.ncf_number or tx.encf_number or tx.invoice_number,
                nota.currency, nota.total)
    return _serialize(nota)


def _serialize(nota: BillingTransaction) -> Dict[str, Any]:
    regime = REGIME_NCF if nota.ncf_number else ("ecf" if nota.encf_number else None)
    doc_type = nota.ncf_type or nota.encf_type
    return {
        "id": nota.id,
        "invoice_number": nota.invoice_number,
        "fiscal_regime": regime,
        "fiscal_number": nota.ncf_number or nota.encf_number,
        "fiscal_doc_type": doc_type,
        "fiscal_doc_label": doc_label(regime, str(doc_type or "")) if regime else None,
        "credits_transaction_id": nota.credits_transaction_id,
        "currency": nota.currency,
        "total": format(nota.total, "f") if nota.total is not None else None,
    }
