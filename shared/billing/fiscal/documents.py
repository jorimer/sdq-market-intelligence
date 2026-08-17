"""Comprobantes fiscales EMITIDOS: consulta, asignación retroactiva y Formato 607.

Tres cosas que el régimen NCF exige y que la ruta de cobro por sí sola no da:

- **Ver qué se emitió.** ``/invoices`` devuelve las facturas del usuario logueado; para
  administrar la numeración hace falta verlas TODAS, con su número, tipo y período.
- **Cerrar las brechas.** Un cobro que ocurrió sin secuencia cargada quedó con
  ``ncf_status='sin_secuencia'`` y sin número (declarado, no rellenado). Al cargar el rango,
  ``assign_pending_numbers`` les asigna correlativo en orden de emisión.
- **Reportarle a la DGII.** El Formato 607 (Ventas de Bienes y Servicios) se presenta mensual
  con cada comprobante emitido. Se GENERA del registro, nunca se transcribe a mano.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any, cast, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.billing.fiscal.types import (
    ECF_NOTA_CREDITO,
    NCF_NOTA_CREDITO,
    REGIME_ECF,
    REGIME_NCF,
    doc_label,
)
from shared.billing.models import BillingTransaction

logger = logging.getLogger("sdq.billing.fiscal.documents")

# Tipo de Ingreso del 607. SDQ vende servicios de inteligencia de mercado: operaciones
# ordinarias del giro. Es una CONSTANTE con nombre, no un "01" suelto en el generador.
TIPO_INGRESO_OPERACIONES = "01"

# Forma de pago del 607 (columnas 17-23). Todo el cobro self-serve entra por PayPal, que
# liquida contra tarjeta de débito/crédito → columna 19.
FORMA_PAGO_TARJETA = "tarjeta"

# Tipo de identificación del comprador (607): 1=RNC, 2=Cédula, 3=Pasaporte. Un RNC dominicano
# tiene 9 dígitos y una cédula 11; sin identificación (consumidor final) la columna va vacía.
_RNC_DIGITS = 9
_CEDULA_DIGITS = 11

# Encabezado canónico del Formato 607 de la DGII, en su orden oficial.
CSV_607_HEADER = [
    "RNC/Cédula/Pasaporte", "Tipo Identificación", "Número Comprobante Fiscal",
    "Número Comprobante Fiscal Modificado", "Tipo de Ingreso", "Fecha Comprobante",
    "Fecha de Retención", "Monto Facturado", "ITBIS Facturado",
    "ITBIS Retenido por Terceros", "ITBIS Percibido", "Retención Renta por Terceros",
    "ISR Percibido", "Impuesto Selectivo al Consumo", "Otros Impuestos/Tasas",
    "Monto Propina Legal", "Efectivo", "Cheque/Transferencia/Depósito",
    "Tarjeta Débito/Crédito", "Venta a Crédito", "Bonos o Certificados de Regalo",
    "Permuta", "Otras Formas de Venta",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _money(value: Any) -> str:
    """Monto con 2 decimales para el 607. Un impuesto que NO aplica vale 0.00 de verdad
    (es una cifra, no un dato ausente); un dato que falta va vacío."""
    return f"{float(value):.2f}" if value is not None else ""


def identification_kind(tax_id: Optional[str]) -> Optional[str]:
    """'1' RNC (9 díg.) · '2' cédula (11 díg.) · None si no hay identificación declarada.
    No adivina: un identificador de largo raro no se fuerza a ninguna de las dos."""
    digits = "".join(ch for ch in (tax_id or "") if ch.isdigit())
    if len(digits) == _RNC_DIGITS:
        return "1"
    if len(digits) == _CEDULA_DIGITS:
        return "2"
    return None


def _period_bounds(period: str) -> Tuple[datetime, datetime]:
    """``'2026-08'`` o ``'202608'`` → [inicio de mes, inicio del siguiente)."""
    raw = (period or "").replace("-", "").strip()
    if len(raw) != 6 or not raw.isdigit():
        raise ValueError(f"Período inválido '{period}'. Use AAAA-MM (p.ej. 2026-08).")
    year, month = int(raw[:4]), int(raw[4:])
    if not 1 <= month <= 12:
        raise ValueError(f"Mes inválido en el período '{period}'.")
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end


def _regime_of(tx: BillingTransaction) -> Optional[str]:
    if tx.ncf_number:
        return REGIME_NCF
    if tx.encf_number:
        return REGIME_ECF
    return None


def _serialize(tx: BillingTransaction, *, client: Optional[Any] = None) -> Dict[str, Any]:
    """Una fila del listado administrativo. El número fiscal SIEMPRE sale con su tipo,
    su etiqueta y su régimen — nunca solo."""
    regime = _regime_of(tx)
    doc_type = tx.ncf_type if regime == REGIME_NCF else (
        tx.encf_type if regime == REGIME_ECF else tx.ncf_type)
    return {
        "id": tx.id,
        "invoice_number": tx.invoice_number,
        "fiscal_regime": regime,
        "fiscal_number": tx.ncf_number or tx.encf_number,
        "fiscal_doc_type": doc_type,
        "fiscal_doc_label": doc_label(regime, str(doc_type or "")) if regime else None,
        "fiscal_status": tx.ncf_status if regime != REGIME_ECF else tx.encf_status,
        "valid_until": tx.ncf_valid_until.isoformat() if tx.ncf_valid_until else None,
        "issued_at": tx.ncf_issued_at.isoformat() if tx.ncf_issued_at else None,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
        "sku": tx.sku,
        "kind": tx.kind,
        "currency": tx.currency,
        "subtotal": format(tx.subtotal, "f") if tx.subtotal is not None else None,
        "tax_amount": format(tx.tax_amount, "f") if tx.tax_amount is not None else None,
        "total": format(tx.total, "f") if tx.total is not None else None,
        "tax_exempt": bool(tx.tax_exempt),
        "country": tx.country,
        "status": tx.status,
        "client_email": getattr(client, "email", None),
        "client_name": getattr(client, "full_name", None),
        "client_tax_id": getattr(client, "tax_id", None),
    }


def list_documents(db: Session, *, period: Optional[str] = None,
                   regime: Optional[str] = None, doc_type: Optional[str] = None,
                   pending_only: bool = False,
                   limit: int = 500) -> List[Dict[str, Any]]:
    """Comprobantes emitidos (y los pendientes de numerar), más recientes primero.
    ``pending_only`` deja solo los cobros que quedaron SIN número fiscal."""
    from shared.auth.models import User

    q = db.query(BillingTransaction, User).outerjoin(User, User.id == BillingTransaction.user_id)
    if period:
        start, end = _period_bounds(period)
        q = q.filter(BillingTransaction.created_at >= start, BillingTransaction.created_at < end)
    if regime == REGIME_NCF:
        q = q.filter(BillingTransaction.ncf_number.isnot(None))
    elif regime == REGIME_ECF:
        q = q.filter(BillingTransaction.encf_number.isnot(None))
    if doc_type:
        q = q.filter(BillingTransaction.ncf_type == doc_type)
    if pending_only:
        q = q.filter(BillingTransaction.ncf_number.is_(None),
                     BillingTransaction.encf_number.is_(None))
    rows = q.order_by(BillingTransaction.created_at.desc()).limit(limit).all()
    return [_serialize(tx, client=user) for tx, user in rows]


def pending_count(db: Session) -> int:
    """Cuántos cobros están esperando número fiscal. Es la brecha, contada."""
    return (db.query(func.count(BillingTransaction.id))
            .filter(BillingTransaction.ncf_number.is_(None),
                    BillingTransaction.encf_number.is_(None))
            .scalar()) or 0


def assign_pending_numbers(db: Session, *, limit: int = 200) -> Dict[str, Any]:
    """Asigna comprobante a los cobros que quedaron sin número, **en orden de emisión**
    (el más viejo primero: el correlativo debe seguir la cronología de las ventas).

    Se detiene limpio cuando la secuencia de un tipo se agota — los que quedan siguen
    declarados como pendientes, no se les inventa número. Devuelve el parte de lo hecho."""
    from shared.billing.fiscal.sequences import FiscalSequenceError, allocate_next
    from shared.settings.service import get_fiscal_regime

    regime = get_fiscal_regime(db)
    rows = (db.query(BillingTransaction)
            .filter(BillingTransaction.ncf_number.is_(None),
                    BillingTransaction.encf_number.is_(None))
            .order_by(BillingTransaction.created_at.asc())
            .limit(limit).all())
    assigned, blocked = [], {}
    now = _utcnow()
    for tx in rows:
        doc_type = str(tx.ncf_type or "02")
        if doc_type in blocked:
            continue
        try:
            fiscal = allocate_next(db, regime=regime, doc_type=doc_type, commit=False)
        except (FiscalSequenceError, ValueError) as e:
            blocked[doc_type] = str(e)
            db.rollback()
            continue
        # cast: SQLAlchemy tipa las columnas como Column[...]; los valores son str/datetime.
        if regime == REGIME_NCF:
            tx.ncf_type = cast(Any, fiscal["doc_type"])
            tx.ncf_number = cast(Any, fiscal["number"])
            tx.ncf_status = cast(Any, "emitido")
            tx.ncf_valid_until = cast(Any, fiscal["expires_at"])
            tx.ncf_issued_at = cast(Any, now)
        else:
            tx.encf_type = cast(Any, fiscal["doc_type"])
            tx.encf_number = cast(Any, fiscal["number"])
            tx.encf_status = cast(Any, "issued")
        db.commit()
        assigned.append({"id": tx.id, "invoice_number": tx.invoice_number,
                         "fiscal_number": fiscal["number"],
                         "fiscal_doc_type": fiscal["doc_type"],
                         "fiscal_doc_label": doc_label(regime, fiscal["doc_type"])})
    logger.info("[fiscal] asignación retroactiva: %d numerados, %d tipos sin rango",
                len(assigned), len(blocked))
    return {"regime": regime, "assigned": assigned, "assigned_count": len(assigned),
            "blocked": blocked, "still_pending": pending_count(db)}


def build_607_rows(db: Session, period: str) -> List[List[str]]:
    """Filas del Formato 607 del período, en el orden oficial de columnas.

    Solo entran comprobantes REALMENTE emitidos: un cobro sin número no se reporta (no
    existe fiscalmente todavía) y aparece en el listado de pendientes, que es donde se ve.

    Una factura **reembolsada SÍ se declara**: el comprobante se emitió y existe. Lo que la
    revierte es su NOTA DE CRÉDITO, que va como fila aparte llevando en la columna «Número
    Comprobante Fiscal Modificado» el número de la factura que corrige. Excluir la original
    dejaría la nota de crédito modificando un comprobante que la declaración nunca mencionó."""
    docs = [d for d in list_documents(db, period=period, limit=10000) if d["fiscal_number"]]
    docs.sort(key=lambda d: (d["created_at"] or "", d["fiscal_number"]))
    modificados = _modified_numbers(db, docs)

    rows: List[List[str]] = []
    for d in docs:
        ident_kind = identification_kind(d["client_tax_id"])
        ident = "".join(ch for ch in (d["client_tax_id"] or "") if ch.isdigit()) if ident_kind else ""
        fecha = (d["created_at"] or "")[:10].replace("-", "")
        rows.append([
            ident, ident_kind or "", d["fiscal_number"] or "", modificados.get(d["id"], ""),
            TIPO_INGRESO_OPERACIONES, fecha, "",
            _money(d["subtotal"]), _money(d["tax_amount"]),
            "0.00", "0.00", "0.00", "0.00", "0.00", "0.00", "0.00",
            "0.00", "0.00", _money(d["total"]), "0.00", "0.00", "0.00", "0.00",
        ])
    return rows


def _modified_numbers(db: Session, docs: List[Dict[str, Any]]) -> Dict[str, str]:
    """``{id de la nota de crédito: número fiscal de la factura que modifica}``.

    La factura modificada puede ser de un período ANTERIOR (se reembolsa en agosto algo
    vendido en julio), así que se busca por id en la base y no entre las filas del período."""
    ids = [d["id"] for d in docs if d["fiscal_doc_type"] in (NCF_NOTA_CREDITO, ECF_NOTA_CREDITO)]
    if not ids:
        return {}
    notas = (db.query(BillingTransaction)
             .filter(BillingTransaction.id.in_(ids))
             .all())
    originales = {n.credits_transaction_id for n in notas if n.credits_transaction_id}
    if not originales:
        return {}
    por_id: Dict[str, str] = {
        str(t.id): str(t.ncf_number or t.encf_number or "")
        for t in db.query(BillingTransaction)
        .filter(BillingTransaction.id.in_(originales)).all()}
    return {str(n.id): por_id.get(str(n.credits_transaction_id or ""), "") for n in notas}


def build_607_csv(db: Session, period: str) -> str:
    """Formato 607 del período como CSV con encabezado. Se GENERA del registro de cobros;
    nunca se transcribe a mano."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_607_HEADER)
    writer.writerows(build_607_rows(db, period))
    return buf.getvalue()
