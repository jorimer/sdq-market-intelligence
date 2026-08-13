"""Brand Intel — API endpoints.

prefix: /api/v1/brand-intel

Holds PRIVATE per-client data, so every read resolves the engagement through
``_resolve`` which enforces the organization boundary. Platform staff (admin and above)
see everything; anyone else sees only their own organization's engagements. An engagement
with no ``organization_id`` is staff-only by construction — an unassigned mandate is never
world-readable by accident.

By owner's decision this module stays outside the public product catalog and is not
exposed through the Data API.
"""
from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole
from shared.database.session import get_db
from modules.brand_intel import report as rpt
from modules.brand_intel import service as svc
from modules.brand_intel.ingest.excel_ingest import ingest_workbook
from modules.brand_intel.ingest.template import build_template, template_filename
from modules.brand_intel.engines.metrics import label_for
from modules.brand_intel.models.models import (
    BrandClient,
    BrandConclusion,
    BrandDecision,
    BrandDiscrepancy,
    BrandEngagement,
    BrandExtraction,
    BrandExtractionCell,
    BrandObservation,
    BrandPlanDocument,
    BrandPlanGoal,
)

logger = logging.getLogger("sdq.api.brand_intel")

router = APIRouter()

_STAFF_ROLES = {UserRole.admin, UserRole.super_admin}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _is_staff(user: User) -> bool:
    return getattr(user, "role", None) in _STAFF_ROLES


def _resolve(db: Session, slug: str, user: User) -> BrandEngagement:
    """Load an engagement and enforce the private-data boundary."""
    eng = svc.get_engagement(db, slug)
    if eng is None:
        raise HTTPException(status_code=404, detail=f"Encargo '{slug}' no encontrado.")
    if not svc.can_access(eng, getattr(user, "organization_id", None), _is_staff(user)):
        # 404, not 403: existence of another client's engagement is itself private.
        raise HTTPException(status_code=404, detail=f"Encargo '{slug}' no encontrado.")
    return eng


# ── schemas ───────────────────────────────────────────────────────────

class ClientIn(BaseModel):
    code: str = Field(..., min_length=2, max_length=40)
    name: str = Field(..., min_length=2, max_length=200)
    organization_id: Optional[str] = None
    notes: Optional[str] = None


class EngagementIn(BaseModel):
    slug: str = Field(..., min_length=2, max_length=60)
    # El cliente al que pertenece el estudio. Se acepta su código o su id; si no viene,
    # `client_name` sigue funcionando y el estudio queda sin agrupar, como los anteriores.
    client: Optional[str] = None
    client_name: str = Field(..., min_length=2, max_length=200)
    focal_brand: str = Field(..., min_length=1, max_length=120)
    market: str = "República Dominicana"
    category: Optional[str] = None
    research_provider: Optional[str] = None
    organization_id: Optional[str] = None
    notes: Optional[str] = None


class DecisionIn(BaseModel):
    title: str = Field(..., min_length=3, max_length=300)
    # La medida: métrica del tracker XOR fuente externa declarada (exactamente una).
    metric_code: Optional[str] = None
    external_measure: Optional[str] = Field(None, max_length=200)
    baseline_wave_code: str
    rationale: Optional[str] = None
    segment: str = "total"
    brand_slug: Optional[str] = None
    target_wave_code: Optional[str] = None
    success_threshold: Optional[float] = None
    owner: Optional[str] = None
    # Quién propone. Habilita la evaluación cara a cara: los planes del cliente y las
    # propuestas de SDQ se miden con la misma vara y su desempeño se reporta aparte.
    origin: str = "cliente"


class FeasibilityIn(BaseModel):
    metric_code: Optional[str] = None
    external_measure: Optional[str] = Field(None, max_length=200)
    baseline_wave_code: str
    segment: str = "total"
    brand_slug: Optional[str] = None
    success_threshold: Optional[float] = None


# ── clientes ──────────────────────────────────────────────────────────

@router.get("/clients", summary="Clientes visibles para el usuario")
def list_clients(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    org = None if _is_staff(user) else getattr(user, "organization_id", None)
    rows = svc.clients(db, organization_id=org)
    counts = svc.engagement_counts_by_client(db, org)
    return [
        {"code": c.code, "name": c.name, "id": c.id,
         "organization_id": c.organization_id,
         "engagements": counts.get(str(c.id), 0)}
        for c in rows
    ]


@router.post("/clients", summary="Crear un cliente", status_code=201)
def create_client(
    payload: ClientIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    if svc.get_client(db, payload.code):
        raise HTTPException(status_code=409,
                            detail=f"Ya existe un cliente con el código '{payload.code}'.")
    row = BrandClient(**payload.model_dump())
    db.add(row)
    db.commit()
    return {"code": row.code, "name": row.name, "id": row.id}


# ── engagements ───────────────────────────────────────────────────────

@router.get("/engagements", summary="Encargos visibles para el usuario")
def list_engagements(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    org = None if _is_staff(user) else getattr(user, "organization_id", None)
    rows = svc.list_engagements(db, organization_id=org)
    codes = {str(c.id): c.code for c in svc.clients(db, organization_id=org)}
    return [
        {
            "slug": e.slug, "client": e.client_name, "focal_brand": e.focal_brand,
            "market": e.market, "category": e.category, "provider": e.research_provider,
            # Waves WITH data: a projection wave holding a frozen forecast is not a wave
            # the client has results for, and counting it overstates the engagement.
            "waves": len(svc.data_waves(db, e.id)),
            "client_code": codes.get(str(e.client_id)) if e.client_id else None,
        }
        for e in rows
    ]


@router.post("/engagements", summary="Crear un encargo", status_code=201)
def create_engagement(
    payload: EngagementIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    if svc.get_engagement(db, payload.slug):
        raise HTTPException(status_code=409, detail=f"Ya existe el encargo '{payload.slug}'.")
    data = payload.model_dump()
    ref = data.pop("client", None)
    client = svc.get_client(db, ref) if ref else None
    if ref and client is None:
        raise HTTPException(status_code=404, detail=f"Cliente '{ref}' no encontrado.")
    if client is not None:
        data["client_id"] = client.id
        data["client_name"] = client.name
        # La organización se hereda del cliente salvo que se declare una: es lo que evita
        # crear un estudio invisible para el propio cliente por olvidar el campo.
        if not data.get("organization_id"):
            data["organization_id"] = client.organization_id
    eng = BrandEngagement(**data)
    db.add(eng)
    db.commit()
    return {"slug": eng.slug, "id": eng.id, "client": client.code if client else None}


@router.get("/engagements/{slug}", summary="Detalle del encargo")
def engagement_detail(
    slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    eng = _resolve(db, slug, user)
    return {
        "slug": eng.slug, "client": eng.client_name, "focal_brand": eng.focal_brand,
        "market": eng.market, "category": eng.category, "provider": eng.research_provider,
        "waves": [
            {"code": w.code, "label": w.label, "order": w.sort_order,
             "period": w.period_date.isoformat() if w.period_date else None,
             "base": w.nominal_base}
            for w in svc.waves(db, eng.id)
        ],
        "brands": [
            {"slug": b.slug, "name": b.name, "is_focal": b.is_focal,
             "in_category_set": b.in_category_set}
            for b in svc.brands(db, eng.id)
        ],
        # Vacío = el encargo es un tracker de marca y usa el diccionario canónico.
        "metrics": [
            {"code": m.code, "label": m.label, "kind": m.kind, "is_core": m.is_core,
             "supports_bands": m.supports_bands}
            for m in (svc.vocabulary_for(db, str(eng.id)).metrics
                      if svc.has_own_metrics(db, str(eng.id)) else [])
        ],
    }


@router.delete("/engagements/{slug}", summary="Eliminar un encargo y todos sus datos")
def delete_engagement(
    slug: str,
    confirm: str = Query(..., description="Repetir el identificador del encargo"),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    """Erase the engagement and every row that belongs to it. There is no undo.

    Requires the slug echoed back in ``confirm``. A DELETE that fires on a URL alone is
    one mis-click or one stale browser tab away from destroying a client's dataset, and
    this is the only endpoint in the module whose damage cannot be undone by re-running
    something. Restricted to admins: the module's ordinary writes are analyst-level, but
    those all leave the data recoverable.
    """
    eng = _resolve(db, slug, user)
    if confirm != slug:
        raise HTTPException(
            status_code=400,
            detail="Para eliminar, repite el identificador exacto del encargo.",
        )
    removed = svc.delete_engagement(db, eng)
    logger.warning("%s eliminó el encargo brand_intel '%s' (%s)", user.email, slug, removed)
    return {"deleted": slug, "removed": removed}


# ── ingest ────────────────────────────────────────────────────────────

@router.get("/template.xlsx", summary="Descargar la plantilla de carga")
def download_template(
    engagement: Optional[str] = Query(None, description="Slug para prellenar la plantilla"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    slug = client = brand = provider = ""
    if engagement:
        eng = _resolve(db, engagement, user)
        slug, client = eng.slug, eng.client_name
        brand, provider = eng.focal_brand, eng.research_provider or ""
    content = build_template(slug, brand, client, provider)
    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={"Content-Disposition":
                 f'attachment; filename="{template_filename(engagement)}"'},
    )


@router.post("/engagements/{slug}/ingest", summary="Cargar el libro del proveedor")
async def ingest(
    slug: str,
    file: UploadFile = File(..., description="Libro .xlsx con la estructura de la plantilla"),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.analyst)),
) -> Dict[str, Any]:
    eng = _resolve(db, slug, user)
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Se espera un archivo .xlsx.")
    content = await file.read()
    try:
        report = ingest_workbook(db, eng, content,
                                 document_name=file.filename or "libro.xlsx")
    except Exception as exc:  # noqa: BLE001 — surface the parse failure, never half-commit
        db.rollback()
        logger.exception("Fallo la ingesta de %s", slug)
        raise HTTPException(status_code=400,
                            detail=f"No se pudo leer el archivo: {exc}") from exc
    db.commit()
    return report.as_dict()


@router.post("/engagements/{slug}/ingest-pdf",
             summary="Cargar una presentación (extracción asistida a revisión)")
async def ingest_pdf(
    slug: str,
    file: UploadFile = File(..., description="Presentación .pdf del proveedor"),
    max_pages: Optional[int] = Query(None, ge=1, le=200,
                                     description="Limitar a las primeras N láminas"),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.analyst)),
) -> Dict[str, Any]:
    """Encola la lectura del mazo y responde de inmediato. No lee ni una lámina aquí.

    Leer un mazo real son decenas de llamadas de visión. Hacerlo dentro de la petición
    moría contra el presupuesto de tiempo del proxy **después de pagar** las llamadas que
    alcanzaba, sin dejar nada. El trabajo vive ahora en su propia fila y la pantalla
    pregunta por el avance con ``GET .../extractions/{id}/status``.
    """
    from modules.brand_intel.ingest import jobs

    eng = _resolve(db, slug, user)
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Se espera un archivo .pdf.")
    content = await file.read()

    try:
        extraction = jobs.queue_extraction(
            db, eng, content, file.filename or "documento.pdf", max_pages)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface the failure, never half-commit
        db.rollback()
        logger.exception("No se pudo encolar la lectura de %s", slug)
        raise HTTPException(status_code=400,
                            detail=f"No se pudo procesar el PDF: {exc}") from exc
    return jobs.job_status(db, extraction)


@router.get("/engagements/{slug}/extractions/{extraction_id}/status",
            summary="Avance de la lectura de un mazo")
def extraction_status(
    slug: str, extraction_id: str, db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Cuántas láminas lleva, si sigue corriendo y por qué falló si falló."""
    from modules.brand_intel.ingest import jobs

    eng = _resolve(db, slug, user)
    row = (db.query(BrandExtraction)
           .filter(BrandExtraction.id == extraction_id,
                   BrandExtraction.engagement_id == eng.id).first())
    if row is None:
        raise HTTPException(status_code=404, detail="Extracción no encontrada.")
    return jobs.job_status(db, row)


@router.post("/engagements/{slug}/extractions/{extraction_id}/resume",
             summary="Reanudar una lectura interrumpida")
def resume_extraction(
    slug: str, extraction_id: str, db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.analyst)),
) -> Dict[str, Any]:
    """Vuelve a despachar un trabajo que quedó a medias.

    Solo sirve mientras el trabajo conserve su PDF: al terminar se suelta, y reanudar un
    trabajo terminado no significa nada. Las láminas ya leídas no se vuelven a pagar.
    """
    from modules.brand_intel.ingest import jobs

    eng = _resolve(db, slug, user)
    row = (db.query(BrandExtraction)
           .filter(BrandExtraction.id == extraction_id,
                   BrandExtraction.engagement_id == eng.id).first())
    if row is None:
        raise HTTPException(status_code=404, detail="Extracción no encontrada.")
    if not row.source_pdf:
        raise HTTPException(
            status_code=409,
            detail="Este trabajo ya no conserva el PDF: vuelve a subir la presentación.")
    jobs._dispatch(str(row.id))
    return jobs.job_status(db, row)


@router.post("/engagements/{slug}/discover",
             summary="Descubrir las olas y las marcas que trae una presentación")
async def discover_structure(
    slug: str,
    file: UploadFile = File(..., description="Presentación .pdf del proveedor"),
    sample: int = Query(5, ge=1, le=15,
                        description="Cuántas láminas leer para el set de marcas"),
    with_brands: bool = Query(True, description="Incluir el pase de marcas (usa el modelo)"),
    with_metrics: bool = Query(
        False,
        description="Proponer también las métricas del estudio. Solo hace falta si NO es "
                    "un tracker de marca: un tracker usa el diccionario canónico.",
    ),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.analyst)),
) -> Dict[str, Any]:
    """Propose the deck's waves and brands. Creates nothing.

    Exists because an engagement is born with a client and a focal brand and no
    structure, while the ingest maps printed labels onto declared waves and brands. A
    client with slides and no workbook had no way to declare them; this reads the deck's
    own vocabulary so a reviewer can adopt it.
    """
    import asyncio

    from modules.brand_intel.ingest import discovery as dsc

    _resolve(db, slug, user)
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Se espera un archivo .pdf.")
    content = await file.read()

    try:
        proposal = await asyncio.to_thread(
            functools.partial(
                dsc.discover_structure, content, sample=sample,
                with_brands=with_brands, with_metrics=with_metrics,
            )
        )
    except Exception as exc:  # noqa: BLE001 — the caller must see why, not a blank panel
        logger.exception("Fallo el descubrimiento de estructura en %s", slug)
        raise HTTPException(status_code=400,
                            detail=f"No se pudo leer el PDF: {exc}") from exc
    return {"document": file.filename, **proposal.as_dict()}


class WaveIn(BaseModel):
    code: str = Field(..., min_length=4, max_length=30)
    label: str = Field(..., min_length=1, max_length=40)
    period_date: Optional[str] = None
    nominal_base: Optional[int] = Field(None, ge=1)


class BrandIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    slug: Optional[str] = Field(None, max_length=60)
    is_focal: bool = False
    in_category_set: bool = True


class MetricIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=60)
    label: str = Field(..., min_length=1, max_length=160)
    # Sin tipo válido se guarda como conteo: `proportion` es el único que habilita banda
    # de confianza, y adivinarlo inventa precisión que el estudio no tiene.
    kind: str = Field("count", max_length=20)
    is_core: bool = False
    higher_is_better: bool = True
    category_denominator: bool = False
    funnel_order: Optional[int] = Field(None, ge=1, le=50)
    description: Optional[str] = None


class StructureIn(BaseModel):
    waves: List[WaveIn] = Field(default_factory=list)
    brands: List[BrandIn] = Field(default_factory=list)
    metrics: List[MetricIn] = Field(default_factory=list)


@router.post("/engagements/{slug}/structure",
             summary="Adoptar las olas y las marcas del encargo")
def adopt_structure(
    slug: str,
    payload: StructureIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.analyst)),
) -> Dict[str, Any]:
    """Create the engagement's waves and brands from a reviewed proposal."""
    eng = _resolve(db, slug, user)
    if not payload.waves and not payload.brands and not payload.metrics:
        raise HTTPException(
            status_code=400,
            detail="No se recibió ninguna ola, marca ni métrica que adoptar.")
    try:
        result = svc.adopt_structure(
            db, eng,
            [w.model_dump() for w in payload.waves],
            [b.model_dump() for b in payload.brands],
            [m.model_dump() for m in payload.metrics],
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/engagements/{slug}/extractions", summary="Extracciones del encargo")
def list_extractions(slug: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    eng = _resolve(db, slug, user)
    rows = (db.query(BrandExtraction)
            .filter(BrandExtraction.engagement_id == eng.id)
            .order_by(BrandExtraction.created_at.desc()).all())
    return [
        {"id": r.id, "document": r.document_name, "pages": r.n_pages,
         "status": r.status, "method": r.method, "model": r.model_used,
         "summary": r.summary, "note": r.note,
         "confirmed_by": r.confirmed_by,
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]


@router.get("/engagements/{slug}/conclusions",
            summary="Lo que AFIRMA el estudio del proveedor, con su lámina")
def list_conclusions(slug: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Las conclusiones leídas del mazo, con el recibo a la vista.

    Esta es la vista interna, y por eso aquí SÍ va la lámina: es donde se comprueba que
    lo que el sistema atribuye al proveedor está efectivamente escrito en su mazo. En el
    informe del cliente esa referencia no aparece — la prosa se leería mecánica y al
    destinatario no le aporta nada. El recibo vive en el registro, no en el texto.
    """
    eng = _resolve(db, slug, user)
    rows = (db.query(BrandConclusion)
            .filter(BrandConclusion.engagement_id == eng.id)
            .order_by(BrandConclusion.page_number).all())
    documents = {
        str(r.id): str(r.document_name)
        for r in db.query(BrandExtraction)
        .filter(BrandExtraction.engagement_id == eng.id).all()
    }
    return {
        "total": len(rows),
        "conclusions": [
            {"id": r.id, "claim": r.claim, "page_number": r.page_number,
             "kind": r.kind, "subjects": r.subjects or [],
             "subject_slugs": r.subject_slugs or [], "topic": r.topic,
             "metric_code": r.metric_code, "direction": r.direction,
             "wave_label": r.wave_label, "wave_code": r.wave_code,
             "confident": r.confident,
             "document": documents.get(str(r.extraction_id or ""))}
            for r in rows
        ],
    }


@router.post("/engagements/{slug}/contrast",
             summary="Contrastar las conclusiones del proveedor con las cifras")
def run_contrast(slug: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Corre el contraste y abre discrepancias donde los datos sostienen lo contrario.

    Idempotente: repetirlo refresca la evidencia de las discrepancias ya abiertas sin
    duplicarlas ni reabrir las que una persona ya trabajó.
    """
    eng = _resolve(db, slug, user)
    out = svc.contrast_conclusions(db, str(eng.id))
    db.commit()
    return out


@router.get("/engagements/{slug}/discrepancies",
            summary="La mesa con el proveedor: desacuerdos defendibles y su estado")
def list_discrepancies(slug: str, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)) -> Dict[str, Any]:
    eng = _resolve(db, slug, user)
    rows = (db.query(BrandDiscrepancy)
            .filter(BrandDiscrepancy.engagement_id == eng.id)
            .order_by(BrandDiscrepancy.created_at).all())
    return {
        "total": len(rows),
        "bloqueantes": sum(1 for r in rows if r.status in svc.BLOCKING_STATES),
        "discrepancies": [
            {"id": r.id, "claim": r.claim, "page_number": r.page_number,
             "subject_slugs": r.subject_slugs or [], "metric_code": r.metric_code,
             "provider_direction": r.provider_direction, "data_note": r.data_note,
             "per_brand": r.per_brand or [], "status": r.status,
             "resolution_note": r.resolution_note, "updated_by": r.updated_by,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows
        ],
    }


@router.patch("/engagements/{slug}/discrepancies/{discrepancy_id}",
              summary="Avanzar una discrepancia de estado")
def patch_discrepancy(
    slug: str, discrepancy_id: str, payload: Dict[str, Any],
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """El contraste abre; solo una persona cierra, con su nombre y su nota."""
    eng = _resolve(db, slug, user)
    try:
        d = svc.update_discrepancy(
            db, str(eng.id), discrepancy_id,
            status=str(payload.get("status") or ""),
            resolution_note=payload.get("resolution_note"),
            actor=str(user.email),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if d is None:
        raise HTTPException(status_code=404, detail="Discrepancia no encontrada.")
    db.commit()
    return {"id": d.id, "status": d.status, "resolution_note": d.resolution_note,
            "updated_by": d.updated_by}


@router.get("/engagements/{slug}/extractions/{extraction_id}",
            summary="Celdas propuestas, para revisión")
def extraction_cells(slug: str, extraction_id: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)) -> Dict[str, Any]:
    eng = _resolve(db, slug, user)
    row = (db.query(BrandExtraction)
           .filter(BrandExtraction.id == extraction_id,
                   BrandExtraction.engagement_id == eng.id).first())
    if row is None:
        raise HTTPException(status_code=404, detail="Extracción no encontrada.")
    cells = (db.query(BrandExtractionCell)
             .filter(BrandExtractionCell.extraction_id == row.id)
             .order_by(BrandExtractionCell.page_number).all())
    # The reviewer is comparing each row against the slide in front of them, and the
    # slide prints "McDonald's" and "Mar '26" — not `mcdonalds` and `2026-03`. The metric
    # was already resolved to its label here; the brand and the wave were not.
    brand_names: Dict[str, str] = {
        str(b.slug): str(b.name) for b in svc.brands(db, str(eng.id))
    }
    wave_labels: Dict[str, str] = {
        str(w.code): str(w.label) for w in svc.waves(db, str(eng.id))
    }
    return {
        "id": row.id, "document": row.document_name, "status": row.status,
        "note": row.note, "summary": row.summary,
        "cells": [
            {"id": c.id, "page": c.page_number, "chart": c.chart_label,
             "wave": wave_labels.get(str(c.wave_code or ""), c.wave_code),
             "brand": brand_names.get(str(c.brand_slug or ""), c.brand_slug),
             "metric": c.metric_code,
             "label": label_for(c.metric_code), "segment": c.segment,
             # El atributo es una DIMENSIÓN de la celda: sin exponerlo, ni la pantalla ni
             # nadie por la API puede comprobar que llegó bien, y el portón de confirmación
             # se estaría cruzando a ciegas sobre las celdas que más lo necesitan.
             "attribute": c.attribute,
             "value": c.value, "base_n": c.base_n,
             "source_method": c.source_method, "validation": c.validation,
             "validation_note": c.validation_note, "included": c.included}
            for c in cells
        ],
    }


class CellDecision(BaseModel):
    cell_id: str
    included: bool


@router.post("/engagements/{slug}/extractions/{extraction_id}/renormalize",
             summary="Recanonizar los cortes de una extracción ya leída")
def renormalize_extraction(
    slug: str, extraction_id: str, db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.analyst)),
) -> Dict[str, Any]:
    """Aplica la canonización de cortes a lo YA extraído y vuelve a validar.

    No relee ni una lámina: cuando el defecto está en cómo se guardó una dimensión, el dato
    sigue en la celda y releer cuesta decenas de llamadas de visión para devolver lo mismo.
    Devuelve además cuántas celdas quedan SIN atributo recuperable —esas sí exigen releer
    con el esquema nuevo—, para que el resultado no insinúe que quedó todo resuelto.
    """
    from modules.brand_intel.ingest.pdf_pipeline import renormalize_staged

    eng = _resolve(db, slug, user)
    row = (db.query(BrandExtraction)
           .filter(BrandExtraction.id == extraction_id,
                   BrandExtraction.engagement_id == eng.id).first())
    if row is None:
        raise HTTPException(status_code=404, detail="Extracción no encontrada.")

    conocidos = [r[0] for r in db.query(BrandObservation.segment)
                 .filter(BrandObservation.engagement_id == eng.id).distinct().all()]
    out = renormalize_staged(db, row, conocidos)
    db.commit()
    return out


@router.post("/engagements/{slug}/extractions/{extraction_id}/confirm",
             summary="Confirmar la extracción y promover a observaciones")
def confirm_extraction(
    slug: str, extraction_id: str,
    decisions: Optional[List[CellDecision]] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.analyst)),
) -> Dict[str, Any]:
    from modules.brand_intel.ingest.pdf_pipeline import confirm_extraction as run_confirm

    eng = _resolve(db, slug, user)
    row = (db.query(BrandExtraction)
           .filter(BrandExtraction.id == extraction_id,
                   BrandExtraction.engagement_id == eng.id).first())
    if row is None:
        raise HTTPException(status_code=404, detail="Extracción no encontrada.")
    if row.status == "confirmed":
        raise HTTPException(status_code=409, detail="Esta extracción ya fue confirmada.")

    for d in decisions or []:
        cell = (db.query(BrandExtractionCell)
                .filter(BrandExtractionCell.id == d.cell_id,
                        BrandExtractionCell.extraction_id == row.id).first())
        if cell is not None:
            cell.included = d.included

    out = run_confirm(db, row, confirmed_by=getattr(user, "email", "—"))
    db.commit()
    return out


# ── analysis ──────────────────────────────────────────────────────────

@router.get("/engagements/{slug}/category", summary="S1 · Categoría, share y divergencia")
def category(slug: str, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return svc.category_analysis(db, _resolve(db, slug, user).id)


@router.get("/engagements/{slug}/attribution", summary="S3 · Atribución mercado vs marca")
def attribution(slug: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return svc.attribution_analysis(db, _resolve(db, slug, user).id)


@router.get("/engagements/{slug}/scenarios",
            summary="S4 · Escenarios, dispersión de reglas y riesgos")
def scenarios(slug: str, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return svc.scenarios_analysis(db, _resolve(db, slug, user).id)


@router.get("/engagements/{slug}/vigilance",
            summary="S5 · Panel de señales y agenda del trimestre")
def vigilance(slug: str, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)) -> Dict[str, Any]:
    eng = _resolve(db, slug, user)
    out = svc.vigilance_analysis(db, eng.id)
    db.commit()          # evaluate_decisions writes verdicts back
    return out


@router.get("/engagements/{slug}/funnel", summary="S1 · Conversión del embudo")
def funnel(slug: str, wave: Optional[str] = Query(None),
           db: Session = Depends(get_db),
           user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return svc.funnel_analysis(db, _resolve(db, slug, user).id, wave)


@router.get("/engagements/{slug}/ticket", summary="S2 · Ticket nominal y real")
def ticket(slug: str, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return svc.ticket_analysis(db, _resolve(db, slug, user).id)


@router.get("/engagements/{slug}/signal-filter", summary="S5 · Filtro de señal")
def signal_filter(slug: str, wave: Optional[str] = Query(None),
                  db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return svc.signal_filter(db, _resolve(db, slug, user).id, wave)


# ── forecasting ───────────────────────────────────────────────────────

@router.get("/engagements/{slug}/forecast/backtest", summary="S4 · Ranking de reglas")
def forecast_backtest(slug: str, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return svc.rule_backtest(db, _resolve(db, slug, user).id)


@router.get("/engagements/{slug}/forecast/track-record", summary="S4 · Track record en vivo")
def forecast_track(slug: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return svc.forecast_track_record(db, _resolve(db, slug, user).id)


@router.post("/engagements/{slug}/forecast/issue", summary="S4 · Congelar pronóstico")
def forecast_issue(slug: str, wave: str = Query(..., description="Código de la ola objetivo"),
                   db: Session = Depends(get_db),
                   user: User = Depends(require_role(UserRole.analyst))) -> Dict[str, Any]:
    eng = _resolve(db, slug, user)
    out = svc.issue_forecasts(db, eng.id, wave)
    if out.get("error"):
        db.rollback()
        raise HTTPException(status_code=400, detail=out["error"])
    db.commit()
    return out


@router.post("/engagements/{slug}/forecast/score", summary="S4 · Puntuar pronósticos")
def forecast_score(slug: str, db: Session = Depends(get_db),
                   user: User = Depends(require_role(UserRole.analyst))) -> Dict[str, Any]:
    eng = _resolve(db, slug, user)
    out = svc.score_pending_forecasts(db, eng.id)
    db.commit()
    return out


# ── decisions ─────────────────────────────────────────────────────────

@router.get("/engagements/{slug}/decisions", summary="S5 · Ledger de decisiones")
def decisions(slug: str, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)) -> Dict[str, Any]:
    eng = _resolve(db, slug, user)
    out = svc.evaluate_decisions(db, eng.id)
    db.commit()
    return out


@router.post("/engagements/{slug}/decisions/check",
             summary="S5 · ¿Es evaluable esta decisión?")
def decision_check(slug: str, payload: FeasibilityIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> Dict[str, Any]:
    eng = _resolve(db, slug, user)
    # El mismo XOR del alta: un check que acepta ambas medidas en silencio miente
    # sobre lo que el registro va a aceptar.
    if bool(payload.metric_code) == bool(payload.external_measure):
        raise HTTPException(
            status_code=422,
            detail="El chequeo requiere exactamente UNA medida: metric_code o "
                   "external_measure.")
    wave = next((w for w in svc.waves(db, eng.id) if w.code == payload.baseline_wave_code), None)
    if wave is None:
        raise HTTPException(status_code=400,
                            detail=f"Ola '{payload.baseline_wave_code}' no existe.")
    return svc.check_decision_feasibility(
        db, eng.id, payload.metric_code, payload.brand_slug, payload.segment,
        wave.id, payload.success_threshold,
        external_measure=payload.external_measure,
    )


@router.post("/engagements/{slug}/decisions", summary="S5 · Registrar una decisión",
             status_code=201)
def create_decision(slug: str, payload: DecisionIn, db: Session = Depends(get_db),
                    user: User = Depends(require_role(UserRole.analyst))) -> Dict[str, Any]:
    eng = _resolve(db, slug, user)
    row, check = _register_decision(db, eng, payload)
    db.commit()
    # A decision that cannot be evaluated is still recorded — with the reason attached,
    # so it can be redesigned rather than quietly re-proposed next quarter.
    return {"id": row.id, "status": row.status, "feasibility": check}


def _register_decision(db: Session, eng: BrandEngagement,
                       payload: DecisionIn) -> tuple:
    """El ÚNICO camino por el que nace una decisión — a mano o adoptando una meta.

    Un segundo camino divergiría en validaciones y factibilidad; la adopción de metas
    reusa este para que una meta adoptada sea indistinguible de una tecleada.
    No commitea: el llamador decide la transacción.
    """
    # La medida es UNA: métrica del tracker o fuente externa. Sin ninguna no hay contra
    # qué emitir veredicto; con ambas no se sabe cuál manda.
    if bool(payload.metric_code) == bool(payload.external_measure):
        raise HTTPException(
            status_code=422,
            detail="La decisión requiere exactamente UNA medida: metric_code (métrica "
                   "del tracker) o external_measure (fuente externa declarada).")
    waves = {w.code: w for w in svc.waves(db, eng.id)}
    base = waves.get(payload.baseline_wave_code)
    if base is None:
        raise HTTPException(status_code=400,
                            detail=f"Ola base '{payload.baseline_wave_code}' no existe.")
    target = waves.get(payload.target_wave_code) if payload.target_wave_code else None
    if payload.target_wave_code and target is None:
        raise HTTPException(status_code=400,
                            detail=f"Ola objetivo '{payload.target_wave_code}' no existe.")

    check = svc.check_decision_feasibility(
        db, eng.id, payload.metric_code, payload.brand_slug, payload.segment,
        base.id, payload.success_threshold,
        external_measure=payload.external_measure,
    )
    # Recorte al tamaño de columna en la ÚNICA frontera de escritura: el texto que
    # viene de un documento (responsable, corte) desborda cualquier largo asumido, y
    # Postgres —a diferencia del SQLite de dev— lo rechaza con un 500.
    from modules.brand_intel.ingest.plans import _clip

    if payload.origin not in ("cliente", "sdq"):
        raise HTTPException(status_code=422,
                            detail="El origen del compromiso debe ser 'cliente' o 'sdq'.")
    row = BrandDecision(
        engagement_id=eng.id, title=payload.title, rationale=payload.rationale,
        origin=payload.origin,
        metric_code=payload.metric_code, external_measure=payload.external_measure,
        segment=_clip(payload.segment, 60) or "total",
        brand_slug=payload.brand_slug, baseline_wave_id=base.id,
        baseline_value=check.get("baseline_value"),
        target_wave_id=target.id if target else None,
        success_threshold=payload.success_threshold,
        owner=_clip(payload.owner, 120),
        status="open" if check["feasible"] else "unevaluable",
        verdict_note=None if check["feasible"] else check["reason"],
        detectable_threshold=check.get("detectable_threshold"),
    )
    db.add(row)
    db.flush()
    return row, check


# ── planes del cliente ────────────────────────────────────────────────

class AdoptGoalIn(BaseModel):
    """Los campos finales de la adopción — lo que el revisor pudo ajustar.

    Todo es opcional: el default de cada campo sale de la meta extraída. El portón
    humano está en el ACTO de adoptar, no en obligar a reteclear lo que el lector leyó.
    """

    title: Optional[str] = Field(None, min_length=3, max_length=300)
    metric_code: Optional[str] = None
    external_measure: Optional[str] = Field(None, max_length=200)
    segment: Optional[str] = None
    brand_slug: Optional[str] = None
    baseline_wave_code: str
    target_wave_code: Optional[str] = None
    success_threshold: Optional[float] = None
    owner: Optional[str] = None


class DismissGoalIn(BaseModel):
    note: str = Field(..., min_length=5, max_length=1000)


def _goal_dict(g: BrandPlanGoal) -> Dict[str, Any]:
    return {
        "id": g.id, "claim": g.claim, "page_number": g.page_number, "kind": g.kind,
        "metric_code": g.metric_code, "segment": g.segment,
        "target_from": g.target_from, "target_to": g.target_to,
        "expected_move": g.expected_move, "owner_declared": g.owner_declared,
        "measure_source": g.measure_source, "confident": g.confident,
        "status": g.status, "adopted_decision_id": g.adopted_decision_id,
        "dismiss_note": g.dismiss_note,
    }


def _plan_dict(p: BrandPlanDocument, goals: List[BrandPlanGoal]) -> Dict[str, Any]:
    return {
        "id": p.id, "filename": p.filename, "title": p.title,
        "source_org": p.source_org, "uploaded_by": p.uploaded_by,
        "page_count": p.page_count, "status": p.status, "note": p.note,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "goals": {
            "total": len(goals),
            "propuestas": sum(1 for g in goals if g.status == "propuesta"),
            "adoptadas": sum(1 for g in goals if g.status == "adoptada"),
            "descartadas": sum(1 for g in goals if g.status == "descartada"),
        },
    }


def _plan_goals(db: Session, plan_id: str) -> List[BrandPlanGoal]:
    return (db.query(BrandPlanGoal)
            .filter(BrandPlanGoal.plan_document_id == plan_id)
            .order_by(BrandPlanGoal.page_number, BrandPlanGoal.created_at)
            .all())


def _resolve_plan(db: Session, eng: BrandEngagement, plan_id: str) -> BrandPlanDocument:
    plan = (db.query(BrandPlanDocument)
            .filter(BrandPlanDocument.id == plan_id,
                    BrandPlanDocument.engagement_id == eng.id)
            .first())
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan no encontrado.")
    return plan


@router.post("/engagements/{slug}/plans", status_code=201,
             summary="S5 · Subir un plan del cliente (el lector propone sus metas)")
async def upload_plan(
    slug: str,
    file: UploadFile = File(..., description="Plan del cliente: .pdf o .html"),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.analyst)),
) -> Dict[str, Any]:
    """Lee el plan sobre su capa de texto y deja sus metas como PROPUESTAS.

    Nada entra al ledger aquí: el lector propone, y solo la adopción (revisión humana)
    convierte una meta en decisión. Síncrono a propósito — la capa de texto son 1-2
    llamadas, no la pasada de visión por lámina de los mazos.
    """
    from modules.brand_intel.ingest import plans as plan_reader
    from modules.brand_intel.ingest.discovery import _page_texts

    eng = _resolve(db, slug, user)
    name = (file.filename or "").lower()
    if not name.endswith((".pdf", ".html", ".htm")):
        raise HTTPException(status_code=400, detail="Se espera un archivo .pdf o .html.")
    content = await file.read()

    # El vocabulario se resuelve ANTES (la sesión de DB no viaja a otro thread); la
    # lectura —cliente Anthropic síncrono, 30-60 s— corre en un worker thread para no
    # congelar el event loop entero (mismo patrón que discover_structure y #491).
    vocab = svc.vocabulary_for(db, str(eng.id))
    try:
        if name.endswith(".pdf"):
            pages = await asyncio.to_thread(_page_texts, content)
            page_count: Optional[int] = len(pages)
        else:
            pages = [plan_reader.html_to_text(content)]
            page_count = None
        reading = await asyncio.to_thread(plan_reader.read_plan, pages, vocab=vocab)
    except Exception as exc:  # noqa: BLE001 — surface the failure, never half-commit
        db.rollback()
        logger.exception("No se pudo leer el plan de %s", slug)
        # Un fallo del lector (sin clave, refusal, corte del API) es del SERVIDOR, no
        # del archivo del usuario: 502 con mensaje saneado, nunca la excepción cruda.
        raise HTTPException(status_code=502,
                            detail="La lectura del plan no está disponible en este "
                                   "momento. El documento no se guardó; intenta de "
                                   "nuevo o revisa el estado del servicio.") from exc

    # Resubir el MISMO archivo relee sobre el mismo plan: el store reemplaza solo las
    # propuestas pendientes y preserva lo que un humano ya adoptó o descartó. Sin esta
    # reconciliación, cada subida duplicaría todas las metas junto a las adoptadas.
    filename = plan_reader._clip(file.filename, 300) or "plan"
    plan = (db.query(BrandPlanDocument)
            .filter(BrandPlanDocument.engagement_id == eng.id,
                    BrandPlanDocument.filename == filename)
            .first())
    if plan is None:
        plan = BrandPlanDocument(engagement_id=eng.id, filename=filename)
        db.add(plan)
    plan.title = plan_reader._clip(reading.title, 300)     # type: ignore[assignment]
    plan.source_org = plan_reader._clip(reading.source_org, 200)  # type: ignore[assignment]
    plan.uploaded_by = getattr(user, "email", None)        # type: ignore[assignment]
    plan.page_count = page_count                           # type: ignore[assignment]
    plan.raw_text = "\n\n".join(pages)[:plan_reader.MAX_CHARS]  # type: ignore[assignment]
    plan.note = (None if reading.goals else                # type: ignore[assignment]
                 "El lector no encontró metas: documento sin capa de texto o sin "
                 "compromisos medibles.")
    db.flush()
    summary = plan_reader.store_plan_goals(db, str(eng.id), str(plan.id), reading)
    _refresh_plan_status(db, plan)
    db.commit()
    return {**_plan_dict(plan, _plan_goals(db, str(plan.id))), "lectura": summary}


@router.get("/engagements/{slug}/plans", summary="S5 · Planes del cliente")
def list_plans(slug: str, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    eng = _resolve(db, slug, user)
    plans = (db.query(BrandPlanDocument)
             .filter(BrandPlanDocument.engagement_id == eng.id)
             .order_by(BrandPlanDocument.created_at.desc())
             .all())
    return [_plan_dict(p, _plan_goals(db, str(p.id))) for p in plans]


@router.get("/engagements/{slug}/plans/{plan_id}",
            summary="S5 · Un plan con sus metas propuestas")
def plan_detail(slug: str, plan_id: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> Dict[str, Any]:
    eng = _resolve(db, slug, user)
    plan = _resolve_plan(db, eng, plan_id)
    goals = _plan_goals(db, str(plan.id))
    return {**_plan_dict(plan, goals), "metas": [_goal_dict(g) for g in goals]}


def _refresh_plan_status(db: Session, plan: BrandPlanDocument) -> None:
    """`revisado` cuando ninguna meta queda propuesta — estado derivado, nunca a mano."""
    db.flush()  # la sesión corre con autoflush=False: sin esto el conteo lee el estado viejo
    pending = (db.query(BrandPlanGoal)
               .filter(BrandPlanGoal.plan_document_id == plan.id,
                       BrandPlanGoal.status == "propuesta")
               .count())
    plan.status = "propuesto" if pending else "revisado"  # type: ignore[assignment]


# ── S6 · las dos series que el operador y el proveedor entregan aparte ──
#
# Ambas entraban por script, y una capacidad que solo yo puedo ejecutar no es una
# capacidad del producto: cada actualización del expediente quedaba atada a una persona.
# Las dos van SÍNCRONAS y sin LLM —son lectores deterministas de Excel, no lecturas de
# modelo—, así que no hace falta el patrón de worker thread de los planes.


@router.post("/engagements/{slug}/sales", status_code=201,
             summary="S6 · Cargar el tablero de ventas del operador")
async def upload_sales(
    slug: str,
    file: UploadFile = File(..., description="Tablero .xlsx con la hoja de detalle"),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.analyst)),
) -> Dict[str, Any]:
    """Carga las jornadas de venta. Idempotente por (encargo, fecha, local).

    El informe de ingesta va SIEMPRE en la respuesta, incluidas las filas descartadas con
    su motivo y las columnas que no se pudieron mapear: una ingesta silenciosa parece
    completa, y así se colaron cuatro columnas de Automac como NULL.
    """
    from modules.brand_intel.ingest import sales as sales_ingest

    eng = _resolve(db, slug, user)
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Se espera un archivo .xlsx.")
    content = await file.read()
    try:
        rows, report = sales_ingest.read_sales_workbook(content)
    except Exception as exc:  # noqa: BLE001 — el fallo es del ARCHIVO: 400 con su motivo
        db.rollback()
        logger.exception("No se pudo leer el tablero de ventas de %s", slug)
        raise HTTPException(status_code=400,
                            detail=f"No se pudo leer el tablero: {exc}") from exc
    if not rows:
        raise HTTPException(
            status_code=400,
            detail="El tablero no dejó ninguna jornada utilizable. "
                   f"Detalle de la lectura: {report.as_dict()}")
    summary = sales_ingest.store_sales(db, str(eng.id), rows,
                                       source_file=file.filename)
    db.commit()
    return {"lectura": report.as_dict(), "guardado": summary}


@router.get("/engagements/{slug}/sales", summary="S6 · Estado de la serie de ventas")
def sales_status(slug: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Qué serie de venta tiene el encargo hoy, con su ventana comparable declarada.

    SIN parámetro de ola, a propósito: la venta la delimita el tablero del operador —su
    propio período y su ventana comparable— y no la fecha de campo de una ola. Aceptar un
    `?wave=` acá daría a entender que la serie se recorta al corte, y no lo hace.
    """
    eng = _resolve(db, slug, user)
    return svc.sales_analysis(db, str(eng.id))


@router.post("/engagements/{slug}/tracker-history", status_code=201,
             summary="S6 · Cargar la matriz histórica del proveedor")
async def upload_tracker_history(
    slug: str,
    file: UploadFile = File(..., description="Matriz .xlsx con la hoja de KPIs"),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.analyst)),
) -> Dict[str, Any]:
    """Carga la matriz ancha de olas históricas. **Solo-si-falta**, nunca sustituye.

    Una observación que ya existe vino de la plantilla CON su base muestral, y esta matriz
    no trae bases: sobrescribirla perdería la banda de confianza, que es lo único que
    convierte un movimiento en veredicto. Las olas que crea quedan renumeradas por fecha,
    porque un histórico insertado al final deja 2018 después de 2026.
    """
    from modules.brand_intel.ingest import tracker_history as hist

    eng = _resolve(db, slug, user)
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Se espera un archivo .xlsx.")
    content = await file.read()
    try:
        readings, report = hist.read_history(content)
    except Exception as exc:  # noqa: BLE001 — fallo del archivo, con su motivo
        db.rollback()
        logger.exception("No se pudo leer la matriz histórica de %s", slug)
        raise HTTPException(status_code=400,
                            detail=f"No se pudo leer la matriz: {exc}") from exc
    if not readings:
        raise HTTPException(
            status_code=400,
            detail="La matriz no dejó ninguna lectura resuelta. Detalle: "
                   f"{report.as_dict()}")
    summary = hist.store_history(db, str(eng.id), readings, source=file.filename)
    db.commit()
    return {"lectura": report.as_dict(), "guardado": summary}


@router.post("/engagements/{slug}/plans/{plan_id}/goals/{goal_id}/adopt",
             summary="S5 · Adoptar una meta del plan como decisión del ledger")
def adopt_goal(slug: str, plan_id: str, goal_id: str, payload: AdoptGoalIn,
               db: Session = Depends(get_db),
               user: User = Depends(require_role(UserRole.analyst))) -> Dict[str, Any]:
    """El portón humano: la meta propuesta se vuelve una BrandDecision por el MISMO
    camino que una decisión tecleada (validación y factibilidad incluidas)."""
    eng = _resolve(db, slug, user)
    plan = _resolve_plan(db, eng, plan_id)
    goal = (db.query(BrandPlanGoal)
            .filter(BrandPlanGoal.id == goal_id,
                    BrandPlanGoal.plan_document_id == plan.id)
            .first())
    if goal is None:
        raise HTTPException(status_code=404, detail="Meta no encontrada.")
    # Claim ATÓMICO: el UPDATE condicionado al estado detiene la doble adopción
    # concurrente (dos pestañas, doble clic) — un chequeo-y-luego-escritura no.
    # Nada se commitea hasta el final: si el registro falla, el rollback lo deshace.
    claimed = (db.query(BrandPlanGoal)
               .filter(BrandPlanGoal.id == goal.id,
                       BrandPlanGoal.status == "propuesta")
               .update({"status": "adoptada"}, synchronize_session="fetch"))
    if not claimed:
        raise HTTPException(status_code=409,
                            detail=f"La meta ya está {goal.status}: solo una meta "
                                   "propuesta se puede adoptar.")

    # Defaults desde la meta extraída; el revisor solo ajusta lo que quiera ajustar.
    # El MODO lo decide cuál medida llega en el payload: el drawer manda una U otra, y
    # Pydantic no distingue null de omitido — heredar la métrica de la meta cuando el
    # revisor eligió fuente externa dejaba AMBAS medidas y el XOR rechazaba la adopción.
    goal_metric = str(goal.metric_code) if goal.metric_code is not None else None
    goal_source = str(goal.measure_source) if goal.measure_source else None
    if goal_source and goal_source.strip().lower() == "tracker":
        # "tracker" es el marcador del lector, no una fuente externa nombrable.
        goal_source = None
    if payload.external_measure:
        metric, external = None, payload.external_measure
    elif payload.metric_code:
        metric, external = payload.metric_code, None
    else:
        metric = goal_metric
        external = None if metric else goal_source
    goal_move = float(goal.expected_move) if goal.expected_move is not None else None
    decision_in = DecisionIn(
        title=payload.title or str(goal.claim)[:300],
        metric_code=metric or None,
        external_measure=external,
        baseline_wave_code=payload.baseline_wave_code,
        rationale=(f"Adoptada del plan «{plan.title or plan.filename}»"
                   + (f", página {goal.page_number}" if goal.page_number else "")
                   + f": «{goal.claim}»"),
        segment=payload.segment or str(goal.segment or "total"),
        brand_slug=payload.brand_slug,
        target_wave_code=payload.target_wave_code,
        success_threshold=(payload.success_threshold
                           if payload.success_threshold is not None
                           else goal_move),
        owner=payload.owner or (str(goal.owner_declared)
                                if goal.owner_declared else None),
    )
    try:
        row, check = _register_decision(db, eng, decision_in)
    except HTTPException:
        # El claim atómico ya marcó la meta: si el registro la rechaza (XOR, ola
        # inexistente), se deshace EXPLÍCITAMENTE — confiar en el teardown de la
        # sesión dejaría la meta "adoptada" sin decisión en sesiones compartidas.
        db.rollback()
        raise
    goal.adopted_decision_id = row.id
    _refresh_plan_status(db, plan)
    db.commit()
    return {"decision_id": row.id, "status": row.status, "feasibility": check,
            "goal": _goal_dict(goal)}


@router.post("/engagements/{slug}/plans/{plan_id}/goals/{goal_id}/dismiss",
             summary="S5 · Descartar una meta propuesta (con motivo)")
def dismiss_goal(slug: str, plan_id: str, goal_id: str, payload: DismissGoalIn,
                 db: Session = Depends(get_db),
                 user: User = Depends(require_role(UserRole.analyst))) -> Dict[str, Any]:
    eng = _resolve(db, slug, user)
    plan = _resolve_plan(db, eng, plan_id)
    goal = (db.query(BrandPlanGoal)
            .filter(BrandPlanGoal.id == goal_id,
                    BrandPlanGoal.plan_document_id == plan.id)
            .first())
    if goal is None:
        raise HTTPException(status_code=404, detail="Meta no encontrada.")
    if goal.status != "propuesta":
        raise HTTPException(status_code=409,
                            detail=f"La meta ya está {goal.status}.")
    goal.status = "descartada"  # type: ignore[assignment]
    goal.dismiss_note = payload.note  # type: ignore[assignment]
    _refresh_plan_status(db, plan)
    db.commit()
    return _goal_dict(goal)


# ── report ────────────────────────────────────────────────────────────

def _validate_wave(db: Session, eng: BrandEngagement, wave: Optional[str]) -> None:
    """Una ola pedida que no existe es un 400, nunca «la última» en silencio.

    ``data_waves`` ignora un corte desconocido a propósito (un corte que rompe el
    informe es peor que uno que no aplica), así que la validación ruidosa vive aquí:
    quien pide una ola concreta debe enterarse de que no hay dato para ella en vez de
    recibir otra con la etiqueta equivocada.
    """
    if not wave:
        return
    codes = [str(w.code) for w in svc.data_waves(db, str(eng.id))]
    if wave not in codes:
        raise HTTPException(
            status_code=400,
            detail=(f"La ola '{wave}' no tiene dato en este encargo. "
                    f"Olas disponibles: {', '.join(codes) or 'ninguna'}."))

@router.get("/engagements/{slug}/report", summary="Informe completo (JSON)")
def report_json(slug: str, wave: Optional[str] = Query(
                    None, description="Ola a medir; por defecto la última con dato"),
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> Dict[str, Any]:
    eng = _resolve(db, slug, user)
    _validate_wave(db, eng, wave)
    payload = rpt.build_report(db, eng, wave=wave)
    db.commit()
    return payload


@router.get("/engagements/{slug}/report.html", summary="Informe completo (HTML imprimible)")
def report_html(slug: str, wave: Optional[str] = Query(None),
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> Response:
    eng = _resolve(db, slug, user)
    _validate_wave(db, eng, wave)
    payload = rpt.build_report(db, eng, wave=wave)
    db.commit()
    return Response(content=rpt.render_html(payload), media_type="text/html; charset=utf-8")


@router.get("/engagements/{slug}/mesa.{fmt}",
            summary="Nota técnica para la mesa con el proveedor (PDF/Word)")
def mesa_document(
    slug: str, fmt: str, db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """El documento espejo del informe: aquí SÍ van las láminas y los umbrales.

    Es material de trabajo SDQ ↔ proveedor, nunca del cliente — otro título, otra marca
    de agua, otro endpoint. Con la mesa vacía responde 404 con el motivo: una nota que
    dice «no hay nada que discutir» solo sirve para agendar una reunión que no hace falta.
    """
    from modules.brand_intel import mesa_docs

    if fmt not in ("pdf", "docx"):
        raise HTTPException(status_code=404, detail="Formato no disponible.")
    eng = _resolve(db, slug, user)
    try:
        path = mesa_docs.render(db, eng, fmt=fmt)
    except Exception as exc:  # noqa: BLE001 — el fallo se dice, no se sirve en blanco
        logger.exception("No se pudo renderizar la nota de mesa %s de %s", fmt, slug)
        raise HTTPException(status_code=500,
                            detail=f"No se pudo generar el documento: {exc}") from exc
    if path is None:
        raise HTTPException(status_code=404,
                            detail="La mesa está vacía: no hay discrepancias que "
                                   "documentar para este encargo.")
    with open(path, "rb") as fh:
        content = fh.read()
    media = ("application/pdf" if fmt == "pdf" else
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    return Response(
        content=content, media_type=media,
        headers={"Content-Disposition":
                 f'attachment; filename="SDQ-MIP_nota_mesa_{slug}.{fmt}"'},
    )


@router.get("/engagements/{slug}/report.{fmt}",
            summary="Informe completo como documento (pdf | docx)")
def report_document(
    slug: str, fmt: str,
    wave: Optional[str] = Query(
        None, description="Ola a medir; por defecto la última con dato"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """El informe en PDF o Word, con el chrome de marca de la plataforma.

    El módulo entregaba solo HTML imprimible, contra `docs/REPORT_STANDARD.md`, que pide
    online · PDF · Word. Un cliente que paga un informe espera un documento.
    """
    from modules.brand_intel import report_docs

    if fmt not in ("pdf", "docx"):
        raise HTTPException(status_code=404, detail="Formato no disponible.")
    eng = _resolve(db, slug, user)
    _validate_wave(db, eng, wave)
    payload = rpt.build_report(db, eng, wave=wave)
    # Las tres secciones narrativas del cliente van por la ruta cerebro (doctrina +
    # guard numérico). La degradación es estructural, no promesa: cualquier fallo de la
    # generación cae a la composición determinista, nunca tumba la descarga.
    try:
        ai = rpt.ai_narratives_sync(payload)
    except Exception:  # noqa: BLE001
        logger.exception("Narrativa cerebro no disponible para %s; composición "
                         "determinista", slug)
        ai = {}
    try:
        path = report_docs.render(payload, fmt=fmt, ai=ai)
    except Exception as exc:  # noqa: BLE001 — el fallo se dice, no se sirve en blanco
        logger.exception("No se pudo renderizar el informe %s de %s", fmt, slug)
        raise HTTPException(status_code=500,
                            detail=f"No se pudo generar el documento: {exc}") from exc
    with open(path, "rb") as fh:
        content = fh.read()
    media = ("application/pdf" if fmt == "pdf" else
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    return Response(
        content=content, media_type=media,
        headers={"Content-Disposition":
                 f'attachment; filename="SDQ-MIP_informe_contexto_{slug}.{fmt}"'},
    )
