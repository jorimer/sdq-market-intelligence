"""Servicio del monitor de productos: recálculo de readiness + matriz para la API.

Recorre el catálogo (10 sectores × 3 niveles): para los sectores con producto
registrado calcula el readiness real desde el contrato; para los declarados-pero-no-
cableados persiste readiness 0 (honesto, no inventado). El recálculo lo disparan el
event_bus (`*.updated`) y el botón manual del dashboard.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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

logger = logging.getLogger("sdq.products.service")

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
    (recálculo por evento); si no, todo el catálogo (manual/inicial).

    Capa 2 del lazo de auto-mejora: detecta las TRANSICIONES de publicabilidad (un nivel
    que cruza su umbral) comparando el readiness previo con el nuevo, y avisa a los admins
    «X ya es publicable, revisar para activar». El sistema propone; el dueño activa."""
    targets = [CATALOG_BY_KEY[sector_key]] if sector_key else PRODUCT_CATALOG
    # Snapshot del readiness previo (para detectar cruces de umbral). Solo se notifica un
    # cruce desde una BASE conocida; en el primer cálculo (sin fila previa) no hay aviso.
    prev = {(r.sector_key, r.tier): float(r.readiness)
            for r in db.query(ProductReadiness).all()}
    n = 0
    up: List[Tuple[str, ProductTier, float]] = []   # cruzaron a publicable
    down: List[Tuple[str, ProductTier]] = []        # cayeron bajo el umbral
    for entry in targets:
        product = get_product(entry.sector_key, db)
        for tier in _tiers_for(product):
            if product is None:
                rep = empty_readiness(entry.sector_key, tier, "sector aún no cableado")
            else:
                rep = compute_readiness(product, tier)
            old = prev.get((entry.sector_key, tier.value))
            if old is not None:
                was = can_activate(old, tier)
                now_ok = can_activate(rep["readiness"], tier)
                if not was and now_ok:
                    up.append((entry.sector_key, tier, rep["readiness"]))
                elif was and not now_ok:
                    down.append((entry.sector_key, tier))
            _upsert_readiness(db, rep)
            n += 1
    db.commit()
    try:
        _notify_publishable_transitions(db, up, down)
    except Exception:  # noqa: BLE001 — un fallo de aviso no debe romper el recálculo
        logger.exception("Aviso de cruce de publicabilidad falló")
        db.rollback()
    return {"recomputed": n, "scope": sector_key or "all"}


def _cross_alert_key(sector: str, tier: str) -> str:
    return f"readiness_cross:{sector}:{tier}"


def _notify_publishable_transitions(
    db: Session,
    up: List[Tuple[str, ProductTier, float]],
    down: List[Tuple[str, ProductTier]],
) -> None:
    """Avisa a los admins de los niveles que cruzaron a publicable y limpia el marcador
    de los que cayeron (para re-avisar si vuelven a cruzar). Deduplica por (sector, nivel)
    vía AppSetting, así un recompute repetido no re-spamea mientras siga publicable."""
    from shared.auth.models import User, UserRole
    from shared.notifications.service import notification_service
    from shared.settings.models import AppSetting

    # Reverse: limpiar marcador para que un futuro cruce vuelva a avisar.
    for sector, tier in down:
        row = db.query(AppSetting).filter(
            AppSetting.key == _cross_alert_key(sector, tier.value)).first()
        if row:
            db.delete(row)
    db.commit()

    # Agrupar los cruces por sector (un aviso por producto, listando sus nuevos niveles).
    fresh: Dict[str, List[Tuple[ProductTier, float]]] = {}
    for sector, tier, score in up:
        key = _cross_alert_key(sector, tier.value)
        if db.query(AppSetting).filter(AppSetting.key == key).first():
            continue  # ya avisado para este (sector, nivel)
        fresh.setdefault(sector, []).append((tier, score))
        db.add(AppSetting(key=key, value=datetime.now(timezone.utc).isoformat(),
                          is_secret=False))
    db.commit()
    if not fresh:
        return

    admin_ids = [u.id for u in db.query(User).filter(
        User.is_active.is_(True),
        User.role.in_([UserRole.admin, UserRole.super_admin])).all()]
    if not admin_ids:
        return
    for sector, levels in fresh.items():
        entry = CATALOG_BY_KEY.get(sector)
        name = entry.display_name if entry else sector
        niveles = ", ".join(f"{t.value} ({s:.3f})" for t, s in sorted(
            levels, key=lambda x: x[1], reverse=True))
        title = f"Listo para publicar: {name}"
        body = (f"«{name}» cruzó el umbral de publicación en: {niveles}. "
                f"Revisar en el monitor para activar (la activación es manual).")
        for uid in admin_ids:
            notification_service.create(db, user_id=uid, type="success", title=title, body=body)


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
