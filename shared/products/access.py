"""Resolvedor de entitlements de la superficie comercial de productos (monetización).

Convierte los hooks ya existentes —``AccessTier`` (User.tier) + ``ProductActivation``—
de metadato declarado en **acceso aplicado**. Único chokepoint: toda superficie que
sirva un producto comercial (Pulse / Insight / Deep Dive) pasa por ``can_access`` /
``require_product_access``, nunca por chequeos planos dispersos (misma doctrina que
``role_satisfies`` / ``require_role`` en el eje de rol).

Composición de la decisión para servir (sector, nivel) a un usuario:
1. **Activación** — el (sector, nivel) debe estar publicado (``ProductActivation.is_active``).
   Si no, ``not_published`` → 404 (no se revela la existencia de lo no publicado).
2. **Tier** — el ``AccessTier`` del usuario debe alcanzar el tier requerido por el nivel
   (``TIER_FOR_LEVEL``). Si no, ``tier_required`` → 402 (upsell).

Doctrina de esta fase (decisiones del dueño 2026-06-24): Pulse = login + tier free
(sin ruta anónima); **sin bypass de admin** en la superficie comercial (la
previsualización interna va por los routers de módulo y el monitor); el tier-gate
aplica SOLO a la superficie comercial, no a los endpoints analíticos internos.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import AccessTier, User, tier_satisfies
from shared.database.session import get_db
from shared.products.models import ProductActivation, ProductEntitlement
from shared.products.tiers import ProductTier

# Mapeo nivel comercial → tier de acceso mínimo requerido (decisión del dueño):
# Pulse abierto = incluido en free; Insight = pro; Deep Dive = enterprise.
TIER_FOR_LEVEL = {
    ProductTier.pulse: AccessTier.free,
    ProductTier.insight: AccessTier.pro,
    ProductTier.deep_dive: AccessTier.enterprise,
}


class AccessOutcome(str, enum.Enum):
    """Resultado de resolver el acceso a un (sector, nivel) para un usuario."""

    allowed = "allowed"              # publicado + tier alcanza → servir (200)
    not_published = "not_published"  # no activado → 404 (no se revela existencia)
    tier_required = "tier_required"  # publicado pero tier insuficiente → 402 (upsell)


@dataclass(frozen=True)
class AccessDecision:
    """Decisión de acceso explicable (para servir o para construir el upsell)."""

    outcome: AccessOutcome
    sector_key: str
    tier: ProductTier
    required_tier: AccessTier
    user_tier: AccessTier

    @property
    def allowed(self) -> bool:
        return self.outcome is AccessOutcome.allowed


def required_tier_for(tier: ProductTier) -> AccessTier:
    """Tier de acceso mínimo que exige un nivel comercial."""
    return TIER_FOR_LEVEL[tier]


def _is_activated(db: Session, sector_key: str, tier: ProductTier) -> bool:
    row = (db.query(ProductActivation)
           .filter_by(sector_key=sector_key, tier=tier.value).one_or_none())
    return bool(row and row.is_active)


def has_product_entitlement(db: Session, user_id: str, sector_key: str,
                            tier: ProductTier) -> bool:
    """¿El usuario tiene una compra/otorgamiento ACTIVO y vigente de este (sector, nivel)?
    Honra la expiración (``expires_at`` None = perpetuo) y la revocación (``active``).
    Es el eje de monetización por-producto, independiente del tier de suscripción."""
    if not user_id:
        return False
    # UTC naive: las columnas DateTime son naive (parity SQLite↔Postgres). Comparar contra
    # un naive UTC evita el TIMESTAMP-WITHOUT-TIME-ZONE vs timestamptz en el lado SQL.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return db.query(
        db.query(ProductEntitlement)
        .filter(ProductEntitlement.user_id == user_id,
                ProductEntitlement.sector_key == sector_key,
                ProductEntitlement.tier == tier.value,
                ProductEntitlement.active.is_(True),
                or_(ProductEntitlement.expires_at.is_(None),
                    ProductEntitlement.expires_at > now))
        .exists()
    ).scalar()


def can_access(db: Session, user: User, sector_key: str, tier: ProductTier) -> AccessDecision:
    """Resuelve el acceso de ``user`` al producto (sector, nivel). Puro de HTTP:
    devuelve una ``AccessDecision`` (no levanta). El orden es activación → (tier OR
    compra por-producto) para no filtrar la existencia de productos no publicados a quien
    no tiene acceso. El acceso lo concede el tier de suscripción O un entitlement comprado."""
    required = TIER_FOR_LEVEL[tier]
    user_tier = user.tier or AccessTier.free
    if not _is_activated(db, sector_key, tier):
        outcome = AccessOutcome.not_published
    elif (tier_satisfies(user_tier, required)
          or has_product_entitlement(db, getattr(user, "id", None), sector_key, tier)):
        outcome = AccessOutcome.allowed
    else:
        outcome = AccessOutcome.tier_required
    return AccessDecision(outcome=outcome, sector_key=sector_key, tier=tier,
                          required_tier=required, user_tier=user_tier)


def enforce_access(decision: AccessDecision) -> None:
    """Traduce una decisión denegada al HTTPException correspondiente (español).
    No-op si está permitida. 404 para no-publicado (no revela existencia); 402 para
    tier insuficiente (lleva el upsell: nivel y tier requerido)."""
    if decision.allowed:
        return
    if decision.outcome is AccessOutcome.not_published:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Producto no disponible.")
    # tier_required → 402 Payment Required con datos para el upsell.
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={
            "message": (f"Tu plan ({decision.user_tier.value}) no incluye el nivel "
                        f"{decision.tier.value}. Requiere el plan "
                        f"{decision.required_tier.value} o superior."),
            "tier": decision.tier.value,
            "required_tier": decision.required_tier.value,
            "user_tier": decision.user_tier.value,
        },
    )


def _parse_tier(tier: str) -> ProductTier:
    try:
        return ProductTier(tier)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Nivel inválido '{tier}'. Use pulse | insight | deep_dive.")


async def require_product_access(
    sector: str,
    tier: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AccessDecision:
    """Dependency para rutas ``…/{sector}/{tier}/…`` de la superficie comercial.
    Resuelve el acceso desde los path params y levanta 400/402/404 si corresponde;
    si permite, devuelve la ``AccessDecision`` (el handler ya tiene usuario+sector+nivel
    validados). Análoga a ``require_role`` pero en el eje de contenido/tier."""
    pt = _parse_tier(tier)
    decision = can_access(db, current_user, sector, pt)
    enforce_access(decision)
    return decision
