"""Servicio de suscripciones recurrentes (monetización Fase B3).

Una ``Subscription`` concede un ``AccessTier`` mientras está vigente. ``can_access`` lo
compone con el tier manual y los entitlements (tier OR suscripción OR entitlement), sin
mutar ``User.tier``. En B3b el webhook de PayPal hace ``apply_subscription`` (upsert por
``provider_subscription_id``) ante cada evento del ciclo de vida.

Transversal (``shared/products``, el eje de acceso): no conoce al proveedor de pago, solo
recibe el tier/estado/período ya normalizados. Parity SQLite↔Postgres: ``DateTime`` naive,
comparación de período contra un UTC-naive del lado SQL.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from shared.auth.models import TIER_RANK, AccessTier
from shared.products.models import Subscription

# Estados del proveedor que reconocemos. Solo ``active`` (dentro del período) concede acceso.
VALID_STATUSES = {"active", "cancelled", "expired", "suspended", "past_due"}


class SubscriptionError(ValueError):
    """Datos inválidos para registrar una suscripción (tier o estado fuera de dominio)."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _validate(tier: str, status: str) -> AccessTier:
    try:
        at = AccessTier(tier)
    except ValueError:
        raise SubscriptionError(f"Tier inválido '{tier}'. Use pro | enterprise.")
    if at == AccessTier.free:
        raise SubscriptionError("Una suscripción no puede conceder el tier free.")
    if status not in VALID_STATUSES:
        raise SubscriptionError(f"Estado inválido '{status}'.")
    return at


def _serialize(s: Subscription) -> Dict[str, Any]:
    return {
        "id": s.id, "user_id": s.user_id, "provider": s.provider,
        "provider_subscription_id": s.provider_subscription_id,
        "sku": s.sku, "interval": s.interval, "tier": s.tier,
        "status": s.status,
        "current_period_end": s.current_period_end.isoformat() if s.current_period_end else None,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "cancelled_at": s.cancelled_at.isoformat() if s.cancelled_at else None,
        "note": s.note,
    }


def apply_subscription(db: Session, *, user_id: str, provider: str,
                       provider_subscription_id: str, tier: str, status: str,
                       sku: Optional[str] = None, interval: Optional[str] = None,
                       current_period_end: Optional[datetime] = None,
                       started_at: Optional[datetime] = None,
                       note: Optional[str] = None) -> Dict[str, Any]:
    """Upsert idempotente de una suscripción por ``(provider, provider_subscription_id)``.
    El webhook lo llama ante cada evento del ciclo de vida (created/renewed/cancelled/…),
    actualizando estado y período. ``sku`` (modelo v2) define el alcance del acceso; ``tier``
    se conserva como espejo legacy. ``status='cancelled'`` setea ``cancelled_at`` si falta."""
    at = _validate(tier, status)
    row = (db.query(Subscription)
           .filter_by(provider=provider, provider_subscription_id=provider_subscription_id)
           .one_or_none())
    period_end = _to_naive_utc(current_period_end)
    start = _to_naive_utc(started_at)
    if row is None:
        row = Subscription(
            user_id=user_id, provider=provider,
            provider_subscription_id=provider_subscription_id, tier=at.value, status=status,
            sku=sku, interval=interval,
            current_period_end=period_end, started_at=start or _utcnow(),
            cancelled_at=_utcnow() if status == "cancelled" else None, note=note)
        db.add(row)
    else:
        row.user_id = user_id
        row.tier = at.value
        row.status = status
        if sku is not None:
            row.sku = sku
        if interval is not None:
            row.interval = interval
        if period_end is not None:
            row.current_period_end = period_end
        if start is not None:
            row.started_at = start
        if status == "cancelled" and row.cancelled_at is None:
            row.cancelled_at = _utcnow()
        if note is not None:
            row.note = note
    db.commit()
    return _serialize(row)


def expire_subscription(db: Session, provider: str, provider_subscription_id: str) -> bool:
    """Marca una suscripción como ``expired`` (corta el acceso). False si no existe."""
    row = (db.query(Subscription)
           .filter_by(provider=provider, provider_subscription_id=provider_subscription_id)
           .one_or_none())
    if row is None:
        return False
    row.status = "expired"
    db.commit()
    return True


def active_subscription_tier(db: Session, user_id: str) -> Optional[AccessTier]:
    """El ``AccessTier`` más alto concedido por una suscripción ACTIVA y vigente del usuario,
    o ``None``. "Vigente" = ``status == 'active'`` y dentro del período (``current_period_end``
    None = abierto, o futuro). Es el eje de monetización por-suscripción, compuesto en
    ``can_access`` con el tier manual y los entitlements."""
    if not user_id:
        return None
    now = _utcnow()
    rows: List[Subscription] = (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id,
                Subscription.status == "active",
                or_(Subscription.current_period_end.is_(None),
                    Subscription.current_period_end > now))
        .all())
    best: Optional[AccessTier] = None
    for r in rows:
        try:
            at = AccessTier(r.tier)
        except ValueError:
            continue
        if best is None or TIER_RANK.get(at, -1) > TIER_RANK.get(best, -1):
            best = at
    return best


def list_user_subscriptions(db: Session, user_id: str) -> List[Dict[str, Any]]:
    """Todas las suscripciones de un usuario (activas e históricas), más recientes primero."""
    rows = (db.query(Subscription)
            .filter_by(user_id=user_id)
            .order_by(Subscription.started_at.desc())
            .all())
    return [_serialize(r) for r in rows]


# ── Gestión MANUAL (aprovisionamiento por admin, cobro fuera de plataforma) ──
# Mientras no hay pasarela (Fase 3), el admin da de alta/cambia/baja la suscripción a mano.
# Provider ``manual`` para distinguirla de las del proveedor de pago (paypal/azul).
MANUAL_PROVIDER = "manual"


def tier_for_sku(sku: str) -> AccessTier:
    """Tier ESPEJO (legacy/display) de un SKU de suscripción: enterprise→enterprise, el resto
    (insight:*/all_access)→pro. El alcance real lo define ``sku_grants_access``, no el tier."""
    from shared.billing.skus import parse_sku

    kind, _ = parse_sku(sku)
    return AccessTier.enterprise if kind == "enterprise" else AccessTier.pro


def set_manual_subscription(db: Session, *, user_id: str, sku: Optional[str] = None,
                            tier: Optional[str] = None, interval: Optional[str] = None,
                            current_period_end: Optional[datetime] = None,
                            note: Optional[str] = None) -> Dict[str, Any]:
    """Alta o CAMBIO de la suscripción manual de un usuario (una sola por usuario).

    Modelo v2: pasar ``sku`` (insight:{sector} / all_access / enterprise) — define el alcance;
    el ``tier`` espejo se deriva. ``tier`` suelto se acepta por compat (sub legacy sin alcance
    por-sector). Si ya existe una manual, la actualiza y reactiva (limpia ``cancelled_at``)."""
    import uuid

    if sku:
        from shared.billing.skus import SkuError, is_subscription_sku, validate_sku
        try:
            validate_sku(sku)
            if not is_subscription_sku(sku):
                raise SubscriptionError(f"El SKU '{sku}' no es una suscripción.")
        except SkuError as e:
            raise SubscriptionError(str(e))
        at = tier_for_sku(sku)
    elif tier:
        at = _validate(tier, "active")
    else:
        raise SubscriptionError("Indicá 'sku' (recomendado) o 'tier'.")

    period_end = _to_naive_utc(current_period_end)
    row = (db.query(Subscription)
           .filter_by(user_id=user_id, provider=MANUAL_PROVIDER)
           .order_by(Subscription.started_at.desc())
           .first())
    if row is None:
        row = Subscription(
            user_id=user_id, provider=MANUAL_PROVIDER,
            provider_subscription_id=f"manual-{uuid.uuid4().hex}", tier=at.value, sku=sku,
            interval=interval, status="active", current_period_end=period_end,
            started_at=_utcnow(), cancelled_at=None, note=note)
        db.add(row)
    else:
        row.tier = at.value
        row.sku = sku
        row.interval = interval
        row.status = "active"
        row.current_period_end = period_end
        row.cancelled_at = None  # reactivar limpia la baja previa (nota B3a)
        if note is not None:
            row.note = note
    db.commit()
    return _serialize(row)


def subscription_grants(db: Session, user_id: str, sector_key: str, tier: str) -> bool:
    """¿Alguna suscripción ACTIVA y vigente del usuario concede acceso a (sector, tier)?

    Modelo v2: cada sub lleva un ``sku`` cuyo alcance resuelve ``sku_grants_access`` (un
    ``insight:banking`` abre solo banking; ``all_access`` todos los Insight; ``enterprise``
    todo). Suscripciones legacy sin ``sku`` caen al mapeo por tier (pro→insight, ent→deep_dive).
    """
    from shared.billing.skus import sku_grants_access
    from shared.products.tiers import ProductTier

    if not user_id:
        return False
    now = _utcnow()
    rows: List[Subscription] = (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id, Subscription.status == "active",
                or_(Subscription.current_period_end.is_(None),
                    Subscription.current_period_end > now))
        .all())
    # Nivel requerido → tier de acceso mínimo (para el fallback legacy por tier).
    from shared.products.access import TIER_FOR_LEVEL
    from shared.auth.models import tier_satisfies
    try:
        required = TIER_FOR_LEVEL[ProductTier(tier)]
    except (ValueError, KeyError):
        required = None
    for r in rows:
        if r.sku:
            if sku_grants_access(r.sku, sector_key, tier):
                return True
        elif required is not None:  # legacy tier-only
            try:
                if tier_satisfies(AccessTier(r.tier), required):
                    return True
            except ValueError:
                continue
    return False


def cancel_subscription(db: Session, subscription_id: str) -> bool:
    """Da de baja una suscripción por id (``cancelled`` + ``cancelled_at``). Corta el acceso
    que concedía. False si no existe. Sirve para la baja manual desde la consola de admin."""
    row = db.query(Subscription).filter_by(id=subscription_id).one_or_none()
    if row is None:
        return False
    row.status = "cancelled"
    if row.cancelled_at is None:
        row.cancelled_at = _utcnow()
    db.commit()
    return True
