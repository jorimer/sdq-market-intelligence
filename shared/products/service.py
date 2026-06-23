"""Servicio del monitor de productos: recálculo de readiness + matriz para la API.

Recorre el catálogo (10 sectores × 3 niveles): para los sectores con producto
registrado calcula el readiness real desde el contrato; para los declarados-pero-no-
cableados persiste readiness 0 (honesto, no inventado). El recálculo lo disparan el
event_bus (`*.updated`) y el botón manual del dashboard.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.products.activation import ACTIVATION_THRESHOLD, can_activate
from shared.products.models import ProductActivation, ProductReadiness
from shared.products.readiness import compute_readiness, empty_readiness
from shared.products.registry import (
    CATALOG_BY_KEY,
    PRODUCT_CATALOG,
    get_product,
    is_implemented,
)
from shared.products.tiers import ProductTier

# Los 3 niveles estándar (para sectores aún sin manifiesto propio).
_STD_TIERS = [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive]


def _tiers_for(product) -> List[ProductTier]:
    if product is None:
        return _STD_TIERS
    return product.product_manifest().tiers()


def _upsert_readiness(db: Session, rep: Dict[str, Any]) -> None:
    row = (db.query(ProductReadiness)
           .filter_by(sector_key=rep["sector_key"], tier=rep["tier"]).one_or_none())
    if row is None:
        row = ProductReadiness(sector_key=rep["sector_key"], tier=rep["tier"])
        db.add(row)
    row.g1, row.g2, row.g3 = rep["g1"], rep["g2"], rep["g3"]
    row.g4, row.g5, row.readiness = rep["g4"], rep["g5"], rep["readiness"]
    row.detail = rep["detail"]
    row.computed_at = datetime.now(timezone.utc)


def recompute_readiness(db: Session, sector_key: Optional[str] = None) -> Dict[str, Any]:
    """Recalcula y persiste el readiness. Si ``sector_key`` viene, solo ese sector
    (recálculo por evento); si no, todo el catálogo (manual/inicial)."""
    targets = [CATALOG_BY_KEY[sector_key]] if sector_key else PRODUCT_CATALOG
    n = 0
    for entry in targets:
        product = get_product(entry.sector_key, db)
        for tier in _tiers_for(product):
            if product is None:
                rep = empty_readiness(entry.sector_key, tier, "sector aún no cableado")
            else:
                rep = compute_readiness(product, tier)
            _upsert_readiness(db, rep)
            n += 1
    db.commit()
    return {"recomputed": n, "scope": sector_key or "all"}


def build_matrix(db: Session) -> Dict[str, Any]:
    """Matriz sector × nivel con readiness + activación + si es activable (para la API)."""
    readiness = {(r.sector_key, r.tier): r for r in db.query(ProductReadiness).all()}
    activation = {(a.sector_key, a.tier): a for a in db.query(ProductActivation).all()}

    sectors: List[Dict[str, Any]] = []
    for entry in PRODUCT_CATALOG:
        implemented = is_implemented(entry.sector_key)  # sin instanciar el producto
        levels = []
        for tier in _STD_TIERS:
            pr = readiness.get((entry.sector_key, tier.value))
            act = activation.get((entry.sector_key, tier.value))
            score = float(pr.readiness) if pr else 0.0
            levels.append({
                "tier": tier.value,
                "readiness": round(score, 4),
                "gates": ({"g1": pr.g1, "g2": pr.g2, "g3": pr.g3, "g4": pr.g4, "g5": pr.g5}
                          if pr else None),
                "detail": pr.detail if pr else None,
                "threshold": ACTIVATION_THRESHOLD[tier],
                "can_activate": can_activate(score, tier),
                "is_active": bool(act.is_active) if act else False,
                "computed_at": pr.computed_at.isoformat() if pr and pr.computed_at else None,
            })
        sectors.append({
            "sector_key": entry.sector_key, "display_name": entry.display_name,
            "source": entry.source, "module_hint": entry.module_hint,
            "implemented": implemented, "levels": levels,
        })
    return {"sectors": sectors, "thresholds": {t.value: v for t, v in ACTIVATION_THRESHOLD.items()}}


def sector_detail(db: Session, sector_key: str) -> Dict[str, Any]:
    """Detalle de un sector (para GET /readiness/{sector})."""
    matrix = build_matrix(db)
    for s in matrix["sectors"]:
        if s["sector_key"] == sector_key:
            return s
    raise ValueError(f"Sector '{sector_key}' no está en el catálogo.")
