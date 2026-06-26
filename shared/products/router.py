"""API del monitor de productos + entrega de la superficie comercial — ``/api/v1/products``.

Transversal (vive en ``shared/``). Dos planos:
- **Monitor** (lecturas: cualquier autenticado; activación/recálculo: admin jerárquico).
- **Entrega comercial** (``/{sector}/{tier}/report`` y ``/download``): gateada por
  ``require_product_access`` (activación + tier, sin bypass de rol). Errores en español.
"""
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole
from shared.database.session import get_db
from shared.narrative.lang_context import resolve_request_lang
from shared.products.access import (
    AccessDecision,
    AccessOutcome,
    can_access,
    require_product_access,
    staff_can_preview,
)
from shared.products.activation import ActivationError, activate, deactivate
from shared.products.anonymization import AnonymizationError
from shared.products.entitlements import (
    EntitlementError,
    grant_entitlement,
    list_user_entitlements,
    revoke_entitlement,
)
from shared.products.assembler import (
    assemble_product_content,
    assemble_product_report,
    assemble_sample_report,
    supports_sample,
)
from shared.products.models import SampleGrant
from shared.products.registry import CATALOG_BY_KEY, PRODUCT_CATALOG, get_product
from shared.products.service import build_matrix, recompute_readiness, sector_detail
from shared.products.tiers import ProductTier

router = APIRouter()


def _parse_tier(tier: str) -> ProductTier:
    try:
        return ProductTier(tier)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail=f"Nivel inválido '{tier}'. Use pulse | insight | deep_dive.")


def _require_sector(sector: str) -> str:
    if sector not in CATALOG_BY_KEY:
        raise HTTPException(status_code=404, detail=f"Sector '{sector}' no está en el catálogo.")
    return sector


@router.get("/readiness", summary="Matriz de readiness sector × nivel + activación")
async def get_readiness(db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return build_matrix(db)


@router.get("/readiness/{sector}", summary="Detalle de readiness de un sector")
async def get_sector_readiness(sector: str, db: Session = Depends(get_db),
                               current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return sector_detail(db, _require_sector(sector))


@router.post("/readiness/recompute", summary="Recalcular readiness (admin)")
async def post_recompute(db: Session = Depends(get_db),
                         current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    res = recompute_readiness(db)
    return {**res, "matrix": build_matrix(db)}


@router.post("/{sector}/{tier}/activate", summary="Exponer al público (admin, gated)")
async def post_activate(sector: str, tier: str, db: Session = Depends(get_db),
                        current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    sector = _require_sector(sector)
    pt = _parse_tier(tier)
    try:
        row = activate(db, sector, pt, user_id=current_user.id)
    except ActivationError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"sector_key": sector, "tier": pt.value, "is_active": row.is_active,
            "activated_at": row.activated_at.isoformat() if row.activated_at else None}


@router.post("/{sector}/{tier}/deactivate", summary="Retirar del acceso público (admin)")
async def post_deactivate(sector: str, tier: str, db: Session = Depends(get_db),
                          current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    sector = _require_sector(sector)
    pt = _parse_tier(tier)
    row = deactivate(db, sector, pt)
    return {"sector_key": sector, "tier": pt.value, "is_active": row.is_active}


@router.get("/catalog", summary="Catálogo de consumo del usuario (productos publicados)")
async def get_catalog(db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Vista de consumo del usuario: solo los niveles PUBLICADOS, con su estado de
    acceso resuelto por ``can_access`` (sin duplicar el mapeo nivel→tier en el cliente).
    Un nivel no publicado no aparece (no se revela). ``unlocked`` indica si el tier del
    usuario lo alcanza; si no, ``required_tier``+``price_band`` alimentan el upsell."""
    user_tier = (current_user.tier.value if current_user.tier else "free")
    # Staff interno (super_admin) ve los productos publicados como "vista interna" aunque
    # su tier no los alcance (QA del catálogo sin auto-concederse un tier comercial).
    is_staff = staff_can_preview(current_user)
    # Muestras ya descargadas por el usuario: set de (sector, nivel) en una sola query.
    used_samples = {
        (g.sector_key, g.tier)
        for g in db.query(SampleGrant).filter_by(user_id=current_user.id).all()
    }
    sectors = []
    for entry in PRODUCT_CATALOG:
        product = get_product(entry.sector_key, db)
        if product is None:
            continue
        manifest = product.product_manifest()
        has_sample = supports_sample(product)
        levels = []
        for tier in manifest.tiers():
            decision = can_access(db, current_user, entry.sector_key, tier)
            if decision.outcome is AccessOutcome.not_published:
                continue  # consumo solo ve lo publicado
            spec = manifest.require_level(tier)
            # Vista interna: un nivel bloqueado por tier se desbloquea para el staff, marcado
            # como staff_preview (no es compra del cliente). No aplica a lo no-publicado.
            staff_preview = (not decision.allowed
                             and decision.outcome is AccessOutcome.tier_required and is_staff)
            unlocked = decision.allowed or staff_preview
            # La muestra solo aplica a niveles bloqueados (no para quien ya los ve), si el
            # producto la ofrece y el usuario no la gastó todavía (una por sector/nivel).
            sample_available = (
                not unlocked and has_sample
                and (entry.sector_key, tier.value) not in used_samples
            )
            levels.append({
                "tier": tier.value,
                "unlocked": unlocked,
                "staff_preview": staff_preview,
                "required_tier": decision.required_tier.value,
                "price_band": spec.price_band,
                "audience": spec.audience,
                "sample_available": sample_available,
            })
        if levels:
            sectors.append({"sector_key": entry.sector_key,
                            "display_name": entry.display_name, "levels": levels})
    return {"sectors": sectors, "user_tier": user_tier}


@router.get("/{sector}/scope-options", summary="Entidades elegibles de los niveles nombrados")
async def get_scope_options(sector: str, db: Session = Depends(get_db),
                            current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Opciones de entidad para el selector de Insight/Deep Dive del catálogo. Vacío si el
    sector no expone ``scope_options`` (el front cae al input libre). No revela acceso: son
    los nombres del universo del sector, ya disponibles en su selector interno."""
    _require_sector(sector)
    product = get_product(sector, db)
    fn = getattr(product, "scope_options", None) if product is not None else None
    options = fn() if callable(fn) else []
    return {"sector": sector, "options": options}


# ─── Entrega comercial (gateada por tier + activación) ──────────────────
#
# Un único handler genérico sirve los 10 sectores vía el contrato uniforme
# ``SectorProduct`` (registry). El acceso ya quedó resuelto por la dependency
# ``require_product_access`` ANTES de entrar al handler (404 no-publicado / 402 upsell).

def _resolve_product(sector: str, db: Session):
    product = get_product(sector, db)
    if product is None:  # en catálogo pero sin cablear (no debería llegar: sin activación)
        raise HTTPException(status_code=404, detail="Producto no disponible.")
    return product


@router.get("/{sector}/{tier}/report", summary="Vista in-app del producto (gated por tier)")
async def get_product_report(
    sector: str, tier: str,
    period: Optional[str] = None, scope: Optional[str] = None,
    db: Session = Depends(get_db),
    lang: str = Depends(resolve_request_lang),
    access: AccessDecision = Depends(require_product_access),
) -> Dict[str, Any]:
    """Devuelve el contenido del (sector, nivel) para render in-app: snapshot +
    narrativas + metadato comercial. El gate (activación + tier) ya corrió en la
    dependency. ``scope`` identifica la entidad en Insight/Deep Dive."""
    product = _resolve_product(sector, db)
    try:
        content = await assemble_product_content(
            product, access.tier, period=period or "", scope=scope, lang=lang)
    except AnonymizationError:
        # Invariante del framework violada (un Pulse filtró un nombre): bug, no input.
        raise HTTPException(status_code=500,
                            detail="Error de gobernanza al ensamblar el producto.")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    level = content.level
    snap = content.snapshot
    return {
        "sector_key": sector, "tier": access.tier.value,
        "period": snap.period, "entity_name": snap.entity_name,
        "payload": snap.payload, "narratives": content.narratives,
        "commercial": {
            "price_band": level.price_band, "watermark": level.watermark,
            "audience": level.audience, "cadence": level.cadence,
            "sections": list(level.sections),
            "staff_preview": access.staff_preview,
        },
    }


@router.get("/{sector}/{tier}/download", summary="Descarga PDF del producto (gated por tier)")
async def get_product_pdf(
    sector: str, tier: str,
    period: Optional[str] = None, scope: Optional[str] = None,
    db: Session = Depends(get_db),
    lang: str = Depends(resolve_request_lang),
    access: AccessDecision = Depends(require_product_access),
) -> FileResponse:
    """Ensambla y devuelve el PDF del (sector, nivel). Mismo gate y mismo contenido que
    la vista in-app (vía ``assemble_product_report``, que reusa el snapshot+narrativas)."""
    product = _resolve_product(sector, db)
    try:
        path = await assemble_product_report(
            product, access.tier, period=period or "", scope=scope, lang=lang)
    except AnonymizationError:
        raise HTTPException(status_code=500,
                            detail="Error de gobernanza al ensamblar el producto.")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # El path lo genera el ensamblador (nunca input del usuario). El filename sí
    # interpola `period` del query: lo saneamos a [A-Za-z0-9_-] por higiene del header.
    safe_period = re.sub(r"[^A-Za-z0-9_-]", "", period or "latest") or "latest"
    filename = f"SDQ_{sector}_{access.tier.value}_{safe_period}.pdf"
    return FileResponse(path=path, media_type="application/pdf", filename=filename)


@router.get("/{sector}/{tier}/sample", summary="Descargar la muestra (una vez por nivel)")
async def get_product_sample(
    sector: str, tier: str,
    db: Session = Depends(get_db),
    lang: str = Depends(resolve_request_lang),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Muestra de conversión: PDF watermarked con datos demo sintéticos de un nivel que el
    usuario NO tiene desbloqueado. Limitada a **una vez por (usuario, sector, nivel)**.
    Disponible solo para productos publicados; si el usuario ya tiene acceso, no gasta la
    muestra (409, que descargue el real). Errores en español."""
    sector = _require_sector(sector)
    pt = _parse_tier(tier)
    decision = can_access(db, current_user, sector, pt)
    if decision.outcome is AccessOutcome.not_published:
        raise HTTPException(status_code=404, detail="Producto no disponible.")
    if decision.allowed:
        raise HTTPException(status_code=409,
                            detail="Ya tienes acceso a este nivel; descarga el reporte completo.")
    product = _resolve_product(sector, db)
    if not supports_sample(product):
        raise HTTPException(status_code=404, detail="Muestra no disponible para este producto.")
    # ¿ya descargó la muestra de este (sector, nivel)? (chequeo barato antes de generar)
    already = (db.query(SampleGrant)
               .filter_by(user_id=current_user.id, sector_key=sector, tier=pt.value).one_or_none())
    if already is not None:
        raise HTTPException(status_code=409, detail="Ya descargaste la muestra de este producto.")
    try:
        path = await assemble_sample_report(product, pt, lang=lang)
    except AnonymizationError:
        raise HTTPException(status_code=500,
                            detail="Error de gobernanza al ensamblar la muestra.")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # Registrar el grant: la unicidad (user, sector, tier) cierra la carrera entre dos
    # descargas concurrentes (la segunda choca con la constraint → 409).
    db.add(SampleGrant(user_id=current_user.id, sector_key=sector, tier=pt.value,
                       downloaded_at=datetime.now(timezone.utc)))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya descargaste la muestra de este producto.")
    filename = f"SDQ_muestra_{sector}_{pt.value}.pdf"
    return FileResponse(path=path, media_type="application/pdf", filename=filename)


# ─── Entitlements por-producto (aprovisionamiento manual, admin) ───────
#
# La "compra puntual" de un (sector, nivel). En B0 lo otorga el admin a mano (cobro fuera
# de plataforma); en B1 lo creará el webhook de pago. `can_access` ya los honra.

class _GrantBody(BaseModel):
    user_id: str
    sector: str
    tier: str
    expires_at: Optional[datetime] = None
    note: Optional[str] = None


@router.get("/entitlements/{user_id}", summary="Entitlements de un usuario (admin)")
async def get_entitlements(user_id: str, db: Session = Depends(get_db),
                           current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    return {"user_id": user_id, "entitlements": list_user_entitlements(db, user_id)}


@router.post("/entitlements", summary="Otorgar acceso por-producto (admin)")
async def post_grant_entitlement(body: _GrantBody, db: Session = Depends(get_db),
                                 current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    target = db.query(User).filter(User.id == body.user_id).one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    try:
        return grant_entitlement(
            db, user_id=body.user_id, sector_key=body.sector, tier=body.tier,
            granted_by=current_user.id, expires_at=body.expires_at, note=body.note)
    except EntitlementError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/entitlements/{entitlement_id}/revoke", summary="Revocar entitlement (admin)")
async def post_revoke_entitlement(entitlement_id: str, db: Session = Depends(get_db),
                                  current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    if not revoke_entitlement(db, entitlement_id):
        raise HTTPException(status_code=404, detail="Entitlement no encontrado.")
    return {"id": entitlement_id, "active": False}
