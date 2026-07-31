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
    BrandDecision,
    BrandEngagement,
    BrandExtraction,
    BrandExtractionCell,
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

class EngagementIn(BaseModel):
    slug: str = Field(..., min_length=2, max_length=60)
    client_name: str = Field(..., min_length=2, max_length=200)
    focal_brand: str = Field(..., min_length=1, max_length=120)
    market: str = "República Dominicana"
    category: Optional[str] = None
    research_provider: Optional[str] = None
    organization_id: Optional[str] = None
    notes: Optional[str] = None


class DecisionIn(BaseModel):
    title: str = Field(..., min_length=3, max_length=300)
    metric_code: str
    baseline_wave_code: str
    rationale: Optional[str] = None
    segment: str = "total"
    brand_slug: Optional[str] = None
    target_wave_code: Optional[str] = None
    success_threshold: Optional[float] = None
    owner: Optional[str] = None


class FeasibilityIn(BaseModel):
    metric_code: str
    baseline_wave_code: str
    segment: str = "total"
    brand_slug: Optional[str] = None
    success_threshold: Optional[float] = None


# ── engagements ───────────────────────────────────────────────────────

@router.get("/engagements", summary="Encargos visibles para el usuario")
def list_engagements(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    org = None if _is_staff(user) else getattr(user, "organization_id", None)
    rows = svc.list_engagements(db, organization_id=org)
    return [
        {
            "slug": e.slug, "client": e.client_name, "focal_brand": e.focal_brand,
            "market": e.market, "category": e.category, "provider": e.research_provider,
            # Waves WITH data: a projection wave holding a frozen forecast is not a wave
            # the client has results for, and counting it overstates the engagement.
            "waves": len(svc.data_waves(db, e.id)),
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
    eng = BrandEngagement(**payload.model_dump())
    db.add(eng)
    db.commit()
    return {"slug": eng.slug, "id": eng.id}


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
        report = ingest_workbook(db, eng, content)
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
    """Read a presentation into staging. Nothing reaches the observations table here."""
    import asyncio

    from modules.brand_intel.ingest.pdf_pipeline import ingest_pdf as run_ingest

    eng = _resolve(db, slug, user)
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Se espera un archivo .pdf.")
    content = await file.read()

    try:
        # The vision pass is synchronous and long; keep it off the event loop.
        report = await asyncio.to_thread(
            run_ingest, db, eng, content, file.filename or "documento.pdf", max_pages,
        )
    except Exception as exc:  # noqa: BLE001 — surface the failure, never half-commit
        db.rollback()
        logger.exception("Fallo la extracción de %s", slug)
        raise HTTPException(status_code=400,
                            detail=f"No se pudo procesar el PDF: {exc}") from exc
    db.commit()
    return report.as_dict()


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
            dsc.discover_structure, content, sample, None, None, with_brands,
            with_metrics,
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
             "value": c.value, "base_n": c.base_n,
             "source_method": c.source_method, "validation": c.validation,
             "validation_note": c.validation_note, "included": c.included}
            for c in cells
        ],
    }


class CellDecision(BaseModel):
    cell_id: str
    included: bool


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
    wave = next((w for w in svc.waves(db, eng.id) if w.code == payload.baseline_wave_code), None)
    if wave is None:
        raise HTTPException(status_code=400,
                            detail=f"Ola '{payload.baseline_wave_code}' no existe.")
    return svc.check_decision_feasibility(
        db, eng.id, payload.metric_code, payload.brand_slug, payload.segment,
        wave.id, payload.success_threshold,
    )


@router.post("/engagements/{slug}/decisions", summary="S5 · Registrar una decisión",
             status_code=201)
def create_decision(slug: str, payload: DecisionIn, db: Session = Depends(get_db),
                    user: User = Depends(require_role(UserRole.analyst))) -> Dict[str, Any]:
    eng = _resolve(db, slug, user)
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
    )
    row = BrandDecision(
        engagement_id=eng.id, title=payload.title, rationale=payload.rationale,
        metric_code=payload.metric_code, segment=payload.segment,
        brand_slug=payload.brand_slug, baseline_wave_id=base.id,
        baseline_value=check.get("baseline_value"),
        target_wave_id=target.id if target else None,
        success_threshold=payload.success_threshold, owner=payload.owner,
        status="open" if check["feasible"] else "unevaluable",
        verdict_note=None if check["feasible"] else check["reason"],
        detectable_threshold=check.get("detectable_threshold"),
    )
    db.add(row)
    db.commit()
    # A decision that cannot be evaluated is still recorded — with the reason attached,
    # so it can be redesigned rather than quietly re-proposed next quarter.
    return {"id": row.id, "status": row.status, "feasibility": check}


# ── report ────────────────────────────────────────────────────────────

@router.get("/engagements/{slug}/report", summary="Informe completo (JSON)")
def report_json(slug: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> Dict[str, Any]:
    eng = _resolve(db, slug, user)
    payload = rpt.build_report(db, eng)
    db.commit()
    return payload


@router.get("/engagements/{slug}/report.html", summary="Informe completo (HTML imprimible)")
def report_html(slug: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> Response:
    eng = _resolve(db, slug, user)
    payload = rpt.build_report(db, eng)
    db.commit()
    return Response(content=rpt.render_html(payload), media_type="text/html; charset=utf-8")
