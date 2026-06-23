"""Gate de activación de acceso público.

Un producto (sector, nivel) solo se EXPONE AL PÚBLICO si su readiness cruza el umbral
del nivel. La activación es siempre **manual y explícita** (decisión del dueño), nunca
automática al cruzar el umbral. Umbrales (decisión 2026-06-23): Insight/Deep Dive
—nombrados, reputación— más exigentes que Pulse —agregado/abierto—.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from shared.products.models import ProductActivation, ProductReadiness
from shared.products.tiers import ProductTier

ACTIVATION_THRESHOLD = {
    ProductTier.pulse: 0.75,
    ProductTier.insight: 0.85,
    ProductTier.deep_dive: 0.85,
}


class ActivationError(ValueError):
    """No se puede activar el producto (readiness bajo umbral o sin calcular)."""


def threshold_for(tier: ProductTier) -> float:
    return ACTIVATION_THRESHOLD[tier]


def can_activate(readiness: float, tier: ProductTier) -> bool:
    """¿El readiness cruza el umbral del nivel? (gate puro, sin DB)."""
    return readiness >= ACTIVATION_THRESHOLD[tier]


def _upsert_activation(db: Session, sector_key: str, tier: ProductTier,
                       is_active: bool, user_id: Optional[str]) -> ProductActivation:
    row = (db.query(ProductActivation)
           .filter_by(sector_key=sector_key, tier=tier.value).one_or_none())
    if row is None:
        row = ProductActivation(sector_key=sector_key, tier=tier.value)
        db.add(row)
    row.is_active = is_active
    if is_active:
        row.activated_by = user_id
        row.activated_at = datetime.now(timezone.utc)
    return row


def activate(db: Session, sector_key: str, tier: ProductTier,
             user_id: Optional[str]) -> ProductActivation:
    """Expone al público (sector, nivel). Rechaza (español) si el readiness no cruza el
    umbral o aún no se ha calculado."""
    pr = (db.query(ProductReadiness)
          .filter_by(sector_key=sector_key, tier=tier.value).one_or_none())
    if pr is None:
        raise ActivationError(
            f"No hay readiness calculado para {sector_key}/{tier.value}; recalcula antes de activar."
        )
    if not can_activate(pr.readiness, tier):
        raise ActivationError(
            f"Readiness {pr.readiness:.2f} no cruza el umbral {ACTIVATION_THRESHOLD[tier]:.2f} "
            f"del nivel {tier.value}: el producto no es publicable todavía."
        )
    row = _upsert_activation(db, sector_key, tier, True, user_id)
    db.commit()
    return row


def deactivate(db: Session, sector_key: str, tier: ProductTier) -> ProductActivation:
    """Retira del acceso público (el producto sigue cableado internamente)."""
    row = _upsert_activation(db, sector_key, tier, False, None)
    db.commit()
    return row
