"""Servicio de entitlements por-producto (monetización Fase B).

Otorgar / revocar / listar el acceso por-producto de un usuario (la "compra puntual"
de un (sector, nivel)). En B0 lo opera el admin a mano (cobro fuera de plataforma);
en B1 el webhook de pago llamará ``grant_entitlement`` con ``source="order"``.

Transversal (``shared/products``): no conoce sectores concretos, solo el catálogo.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.products.models import ProductEntitlement
from shared.products.registry import CATALOG_BY_KEY
from shared.products.tiers import ProductTier


class EntitlementError(ValueError):
    """Datos inválidos para otorgar un entitlement (sector/nivel fuera del catálogo)."""


def _validate(sector_key: str, tier: str) -> ProductTier:
    if sector_key not in CATALOG_BY_KEY:
        raise EntitlementError(f"Sector '{sector_key}' no está en el catálogo.")
    try:
        return ProductTier(tier)
    except ValueError:
        raise EntitlementError(f"Nivel inválido '{tier}'. Use pulse | insight | deep_dive.")


def _serialize(e: ProductEntitlement) -> Dict[str, Any]:
    return {
        "id": e.id, "user_id": e.user_id, "sector_key": e.sector_key, "tier": e.tier,
        "source": e.source, "granted_by": e.granted_by,
        "granted_at": e.granted_at.isoformat() if e.granted_at else None,
        "expires_at": e.expires_at.isoformat() if e.expires_at else None,
        "active": bool(e.active), "note": e.note,
    }


def grant_entitlement(db: Session, *, user_id: str, sector_key: str, tier: str,
                      granted_by: Optional[str], expires_at: Optional[datetime] = None,
                      note: Optional[str] = None, source: str = "manual") -> Dict[str, Any]:
    """Otorga acceso por-producto a un usuario. ``expires_at`` None = perpetuo. Idempotente
    en intención (crea una fila nueva por otorgamiento; revocar marca ``active=False``)."""
    pt = _validate(sector_key, tier)
    # Columnas DateTime naive (parity SQLite↔Postgres): guardar UTC sin tz, igual que la
    # comparación en has_product_entitlement.
    if expires_at is not None and expires_at.tzinfo is not None:
        expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
    row = ProductEntitlement(
        user_id=user_id, sector_key=sector_key, tier=pt.value, source=source,
        granted_by=granted_by, granted_at=datetime.now(timezone.utc).replace(tzinfo=None),
        expires_at=expires_at, active=True, note=note)
    db.add(row)
    db.commit()
    return _serialize(row)


def revoke_entitlement(db: Session, entitlement_id: str) -> bool:
    """Revoca (``active=False``) un entitlement. Devuelve False si no existe."""
    row = db.query(ProductEntitlement).filter_by(id=entitlement_id).one_or_none()
    if row is None:
        return False
    row.active = False
    db.commit()
    return True


def list_user_entitlements(db: Session, user_id: str) -> List[Dict[str, Any]]:
    """Todos los entitlements de un usuario (activos e históricos), más recientes primero."""
    rows = (db.query(ProductEntitlement)
            .filter_by(user_id=user_id)
            .order_by(ProductEntitlement.granted_at.desc())
            .all())
    return [_serialize(r) for r in rows]
