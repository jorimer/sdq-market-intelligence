"""Resolver de audiencia de alertas de tarifa (monetización B2).

¿A quién afecta un cambio de precio de un SKU? Hoy, sin modelo de suscripción formal
(eso llega en B3), el mapeo honesto es por tier:

- ``insight`` (suscripción Insight, plataforma-wide) → usuarios con tier **pro/enterprise
  activos** (los suscriptos a Insight, hoy aprovisionados a mano). Su precio de renovación
  cambia → se les avisa.
- ``deep_dive:{sector}`` / ``special:{slug}`` → compra puntual perpetua: el comprador ya
  fijó su precio y no renueva → no hay suscriptor recurrente → audiencia vacía.

Esta función es la **costura** de B3: cuando exista el registro ``Subscription``, la
audiencia de ``insight`` pasará de "tier >= pro" a "tenedores de suscripción activa" sin
tocar el publicador ni el suscriptor de eventos.
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from shared.auth.models import AccessTier, User
from shared.billing.skus import parse_sku


def affected_subscribers(db: Session, sku: str) -> List[User]:
    """Usuarios a notificar ante un cambio de precio de ``sku``. Lista vacía si el SKU no
    tiene suscriptores recurrentes (compras puntuales) o si el SKU es inválido."""
    try:
        kind, _ref = parse_sku(sku)
    except ValueError:
        return []
    if kind != "insight":
        return []  # solo la suscripción Insight tiene suscriptores recurrentes hoy
    return (db.query(User)
            .filter(User.is_active.is_(True),
                    User.tier.in_([AccessTier.pro, AccessTier.enterprise]))
            .all())
