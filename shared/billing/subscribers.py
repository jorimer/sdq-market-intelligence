"""Resolver de audiencia de alertas de tarifa (monetización B2).

¿A quién afecta un cambio de precio de un SKU? A los **tenedores de una suscripción ACTIVA
de ese SKU** (su precio de renovación cambia → se les avisa). Las compras puntuales
(``deep_dive`` / ``special``) no renuevan → sin suscriptores recurrentes → audiencia vacía.
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from shared.auth.models import User
from shared.billing.skus import is_subscription_sku


def affected_subscribers(db: Session, sku: str) -> List[User]:
    """Usuarios a notificar ante un cambio de precio de ``sku``: los que tienen una
    ``Subscription`` activa de ese SKU. Vacía para compras puntuales o SKU inválido."""
    from shared.products.models import Subscription

    try:
        if not is_subscription_sku(sku):
            return []
    except ValueError:
        return []
    user_ids = {
        s.user_id for s in db.query(Subscription)
        .filter(Subscription.sku == sku, Subscription.status == "active").all()
    }
    if not user_ids:
        return []
    return db.query(User).filter(User.id.in_(user_ids), User.is_active.is_(True)).all()
