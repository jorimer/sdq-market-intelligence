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
from shared.auth.models import AccessTier, User, UserRole, tier_satisfies
from shared.database.session import get_db
from shared.narrative.claude_engine import NarrativeDegradedError
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
from shared.products.subscriptions import (
    SubscriptionError,
    active_subscription_tier,
    cancel_subscription,
    list_user_subscriptions,
    set_manual_subscription,
)
from shared.products.tiers import Granularity, ProductTier

router = APIRouter()

# Mensaje de degradación transitoria de la narrativa IA (rate-limit/outage del servicio de
# análisis o corte de presupuesto). Un producto premium NO se entrega hueco: se responde 503
# (reintento) en vez de un PDF con relleno. Español, orientado al usuario final.
_NARRATIVE_DEGRADED_MSG = (
    "El análisis de este informe no está disponible en este momento por un límite temporal "
    "del servicio de generación. Reintente en unos minutos."
)


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


@router.get("/readiness/audit", summary="Readiness Audit — qué falta por eje + acción")
async def get_readiness_audit(db: Session = Depends(get_db),
                              current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Evaluación multi-eje: por sector × nivel, readiness + cada gate + qué falta + la
    acción concreta para cerrarlo. Mismo dato del monitor (no recalcula ni inventa).
    Incluye ``markdown`` para exportar el documento."""
    from shared.products.audit import build_audit
    return build_audit(db)


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
        # ¿El nivel nombrado necesita que el usuario ELIJA una entidad? Solo si el producto
        # expone su universo (``scope_options``). Los productos de sujeto FIJO (sector
        # nacional: trade, energía…) ignoran el scope → no deben pedir nada.
        requires_scope = callable(getattr(product, "scope_options", None))
        # Tipo de sujeto a elegir → rótulo correcto en el catálogo: "entity" (banco) por
        # defecto, "country" (país, panel) para los índices de riesgo-país (macro/ESG).
        _sk = getattr(product, "scope_kind", None)
        scope_kind = (_sk() if callable(_sk) else _sk) or "entity"
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
            # Solo los niveles nombrados (no Pulse) pueden requerir una entidad elegida.
            named = spec.granularity is not Granularity.system
            levels.append({
                "tier": tier.value,
                "unlocked": unlocked,
                "staff_preview": staff_preview,
                "required_tier": decision.required_tier.value,
                "price_band": spec.price_band,
                "audience": spec.audience,
                "sample_available": sample_available,
                "requires_scope": named and requires_scope,
                "scope_kind": scope_kind,
            })
        if levels:
            sectors.append({"sector_key": entry.sector_key,
                            "display_name": entry.display_name, "levels": levels})
    return {"sectors": sectors, "user_tier": user_tier}


@router.get("/{sector}/periods", summary="Períodos disponibles del producto (para el selector)")
async def get_product_periods(sector: str, db: Session = Depends(get_db),
                              current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Períodos reales del producto (más reciente primero) para el selector del reporte.
    Vacío si el producto no expone ``available_periods`` → el front cae al período global."""
    _require_sector(sector)
    product = get_product(sector, db)
    fn = getattr(product, "available_periods", None) if product is not None else None
    periods = fn() if callable(fn) else []
    return {"sector": sector, "periods": periods}


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
    except NarrativeDegradedError:
        # Narrativa IA degradada a fallback estático en un premium: no se sirve hueco.
        raise HTTPException(status_code=503, detail=_NARRATIVE_DEGRADED_MSG)
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
            # Orden canónico: secciones del nivel + estándar (metodología/fuentes) anexadas.
            "sections": list(content.section_order or level.sections),
            "staff_preview": access.staff_preview,
        },
    }


_DOC_FORMATS = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.get("/{sector}/{tier}/download", summary="Descarga del producto PDF/Word (gated por tier)")
async def get_product_pdf(
    sector: str, tier: str,
    period: Optional[str] = None, scope: Optional[str] = None,
    format: str = "pdf",
    db: Session = Depends(get_db),
    lang: str = Depends(resolve_request_lang),
    access: AccessDecision = Depends(require_product_access),
) -> FileResponse:
    """Ensambla y devuelve el reporte del (sector, nivel) en ``format`` ("pdf" | "docx").
    Mismo gate y mismo contenido que la vista in-app (vía ``assemble_product_report``)."""
    fmt = format if format in _DOC_FORMATS else "pdf"
    product = _resolve_product(sector, db)
    try:
        path = await assemble_product_report(
            product, access.tier, period=period or "", scope=scope, lang=lang, fmt=fmt)
    except NarrativeDegradedError:
        # Narrativa IA degradada a fallback estático en un premium: no se descarga hueco.
        raise HTTPException(status_code=503, detail=_NARRATIVE_DEGRADED_MSG)
    except AnonymizationError:
        raise HTTPException(status_code=500,
                            detail="Error de gobernanza al ensamblar el producto.")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # El path lo genera el ensamblador (nunca input del usuario). El filename sí
    # interpola `period` del query: lo saneamos a [A-Za-z0-9_-] por higiene del header.
    safe_period = re.sub(r"[^A-Za-z0-9_-]", "", period or "latest") or "latest"
    filename = f"SDQ_{sector}_{access.tier.value}_{safe_period}.{fmt}"
    return FileResponse(path=path, media_type=_DOC_FORMATS[fmt], filename=filename)


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


# ─── Suscripciones (aprovisionamiento manual por admin, mientras no hay pasarela) ───
#
# Alta / cambio de plan / baja de la suscripción de un usuario, operadas por el admin
# (cobro fuera de plataforma). El webhook de pago (Fase 3) usará el mismo modelo vía
# ``apply_subscription``. ``can_access`` ya honra la suscripción activa como eje de acceso.

class _SubBody(BaseModel):
    user_id: str
    sku: Optional[str] = None       # v2: insight:{sector} | all_access | enterprise (alcance)
    tier: Optional[str] = None      # legacy: pro | enterprise (sin alcance por-sector)
    interval: Optional[str] = None  # monthly | annual
    current_period_end: Optional[datetime] = None  # None = abierto (sin vencimiento)
    note: Optional[str] = None


@router.get("/subscriptions/{user_id}", summary="Suscripciones de un usuario (admin)")
async def get_subscriptions(user_id: str, db: Session = Depends(get_db),
                            current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    return {"user_id": user_id, "subscriptions": list_user_subscriptions(db, user_id)}


@router.post("/subscriptions", summary="Alta o cambio de plan de la suscripción (admin)")
async def post_set_subscription(body: _SubBody, db: Session = Depends(get_db),
                                current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    """Da de alta o CAMBIA el plan de la suscripción manual del usuario (una por usuario).
    Reactiva si estaba dada de baja. El acceso se concede mientras esté activa y vigente."""
    target = db.query(User).filter(User.id == body.user_id).one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    try:
        return set_manual_subscription(
            db, user_id=body.user_id, sku=body.sku, tier=body.tier, interval=body.interval,
            current_period_end=body.current_period_end, note=body.note)
    except SubscriptionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/subscriptions/{subscription_id}/cancel", summary="Dar de baja una suscripción (admin)")
async def post_cancel_subscription(subscription_id: str, db: Session = Depends(get_db),
                                   current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    if not cancel_subscription(db, subscription_id):
        raise HTTPException(status_code=404, detail="Suscripción no encontrada.")
    return {"id": subscription_id, "status": "cancelled"}


@router.get("/me/plan", summary="Mi plan: tier efectivo + suscripción + accesos por-producto")
async def get_my_plan(db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Vista del usuario de su propio plan: el tier efectivo (el mayor entre el manual y el
    de una suscripción activa), sus suscripciones y sus entitlements por-producto vigentes."""
    manual_tier = current_user.tier or AccessTier.free
    sub_tier = active_subscription_tier(db, current_user.id)
    effective = manual_tier
    if sub_tier is not None and tier_satisfies(sub_tier, manual_tier) and sub_tier != manual_tier:
        # tier efectivo = el más alto entre el manual y el de la suscripción vigente
        effective = sub_tier
    return {
        "manual_tier": manual_tier.value,
        "subscription_tier": sub_tier.value if sub_tier else None,
        "effective_tier": effective.value,
        "subscriptions": list_user_subscriptions(db, current_user.id),
        "entitlements": list_user_entitlements(db, current_user.id),
    }
