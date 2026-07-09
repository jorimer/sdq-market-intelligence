"""Servicio del tarifario gestionado (monetización Fase B1).

Operaciones sobre ``Tariff``: publicar un precio (con vigencia), retirarlo, listar el
tarifario y —el núcleo— **resolver el precio vigente** de un SKU a una fecha. El checkout
de B3 leerá ``price_for`` en vez de cualquier número hardcodeado.

Semántica de vigencia (sin auto-cierre del histórico): el precio vigente a ``at`` es la
fila ``active`` cuya ventana contiene ``at`` (``effective_from <= at`` y ``effective_to``
None o ``> at``) con el ``effective_from`` más reciente. Publicar un precio nuevo con
``effective_from`` futuro deja el anterior vigente hasta esa fecha y lo reemplaza a partir
de ella, sin tocar el histórico (auditable).

Parity SQLite↔Postgres: montos en ``Decimal`` (no float); comparación de fechas contra un
UTC-naive (las columnas ``DateTime`` son naive).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from shared.billing.events import TARIFF_PUBLISHED
from shared.billing.models import Tariff
from shared.billing.skus import INTERVAL_ONCE, SkuError, allowed_intervals, validate_sku
from shared.events.event_bus import event_bus


class TariffError(ValueError):
    """Datos inválidos para publicar un precio (SKU, moneda, monto o vigencia)."""


def _utcnow() -> datetime:
    # UTC naive: las columnas DateTime son naive (parity SQLite↔Postgres).
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_naive_utc(dt: datetime) -> datetime:
    """Normaliza un datetime (aware o naive) a UTC-naive para guardar/comparar."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _coerce_amount(amount: Any) -> Decimal:
    try:
        value = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise TariffError(f"Monto inválido: '{amount}'.")
    if value <= 0:
        raise TariffError("El monto debe ser mayor que cero.")
    return value


def _serialize(t: Tariff, *, at: Optional[datetime] = None) -> Dict[str, Any]:
    at = at or _utcnow()
    is_current = bool(
        t.active
        and t.effective_from <= at
        and (t.effective_to is None or t.effective_to > at)
    )
    scheduled = bool(t.active and t.effective_from > at)
    return {
        "id": t.id,
        "sku": t.sku,
        "interval": t.interval or INTERVAL_ONCE,
        "currency": t.currency,
        "amount": format(t.amount, "f") if t.amount is not None else None,
        "effective_from": t.effective_from.isoformat() if t.effective_from else None,
        "effective_to": t.effective_to.isoformat() if t.effective_to else None,
        "active": bool(t.active),
        "is_current": is_current,
        "scheduled": scheduled,
        "label": t.label,
        "note": t.note,
    }


def create_tariff(db: Session, *, sku: str, amount: Any, currency: str = "USD",
                  interval: str = INTERVAL_ONCE,
                  effective_from: Optional[datetime] = None,
                  effective_to: Optional[datetime] = None,
                  label: Optional[str] = None, note: Optional[str] = None,
                  created_by: Optional[str] = None) -> Dict[str, Any]:
    """Publica un precio para un ``(sku, interval)``. ``interval`` debe ser válido para el SKU
    (once en compras puntuales; monthly/annual en suscripciones). ``effective_from`` None =
    rige desde ahora; ``effective_to`` None = abierto. No edita el histórico."""
    try:
        validate_sku(sku)
    except SkuError as e:
        raise TariffError(str(e))
    interval = (interval or INTERVAL_ONCE).strip()
    if interval not in allowed_intervals(sku):
        raise TariffError(
            f"Intervalo '{interval}' inválido para '{sku}'. Válidos: {', '.join(allowed_intervals(sku))}.")

    cur = (currency or "").strip().upper()
    if len(cur) != 3 or not cur.isalpha():
        raise TariffError(f"Moneda inválida '{currency}'. Use código ISO de 3 letras (p.ej. USD).")

    value = _coerce_amount(amount)
    eff_from = _to_naive_utc(effective_from) if effective_from else _utcnow()
    eff_to = _to_naive_utc(effective_to) if effective_to else None
    if eff_to is not None and eff_to <= eff_from:
        raise TariffError("La vigencia 'hasta' debe ser posterior a 'desde'.")

    # ¿Es un CAMBIO sobre un precio actualmente vigente de ese (sku, interval)? Se resuelve
    # ANTES de insertar para alertar a los suscriptos (B2) solo ante cambios.
    is_change = price_for(db, sku, interval) is not None

    row = Tariff(sku=sku, interval=interval, currency=cur, amount=value, effective_from=eff_from,
                 effective_to=eff_to, active=True, label=label, note=note,
                 created_by=created_by)
    db.add(row)
    db.commit()
    out = _serialize(row)
    # Publicar tras el commit (la alerta corre en su propia sesión; un fallo de notificación
    # no revierte la tarifa ya persistida). Los handlers se suscriben solo en runtime.
    event_bus.publish(TARIFF_PUBLISHED, {
        "sku": sku, "interval": interval, "currency": cur, "amount": format(value, "f"),
        "effective_from": eff_from.isoformat(), "is_change": is_change,
    })
    return out


def withdraw_tariff(db: Session, tariff_id: str) -> bool:
    """Retira (``active=False``) una fila de tarifa. Devuelve False si no existe.
    No borra: el histórico queda para auditoría."""
    row = db.query(Tariff).filter_by(id=tariff_id).one_or_none()
    if row is None:
        return False
    row.active = False
    db.commit()
    return True


def price_for(db: Session, sku: str, interval: str = INTERVAL_ONCE,
              at: Optional[datetime] = None) -> Optional[Tariff]:
    """Precio vigente de ``(sku, interval)`` a la fecha ``at`` (default ahora): la fila
    ``active`` cuya ventana contiene ``at``, con el ``effective_from`` más reciente. ``None``
    si no hay precio vigente (no se debe vender sin tarifa configurada)."""
    moment = _to_naive_utc(at) if at else _utcnow()
    return (db.query(Tariff)
            .filter(Tariff.sku == sku,
                    Tariff.interval == interval,
                    Tariff.active.is_(True),
                    Tariff.effective_from <= moment,
                    or_(Tariff.effective_to.is_(None), Tariff.effective_to > moment))
            .order_by(Tariff.effective_from.desc())
            .first())


def list_tariffs(db: Session, sku: Optional[str] = None,
                 include_inactive: bool = True) -> List[Dict[str, Any]]:
    """Lista el tarifario (todas las filas, vigentes / programadas / históricas), más
    recientes primero. Filtra por ``sku`` si se da; ``include_inactive=False`` oculta las
    retiradas."""
    q = db.query(Tariff)
    if sku is not None:
        q = q.filter(Tariff.sku == sku)
    if not include_inactive:
        q = q.filter(Tariff.active.is_(True))
    rows = q.order_by(Tariff.effective_from.desc()).all()
    now = _utcnow()
    return [_serialize(r, at=now) for r in rows]
