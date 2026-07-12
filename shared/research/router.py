"""API del motor de research custom — ``/api/v1/research``.

Recibe una pregunta libre y devuelve la respuesta con procedencia + el gate de
publicación (informe completo o scoping report). Gateado a usuarios autenticados;
la entrega comercial por-tier (DD Full/Deep Dive) se cablea en la Fase 5.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import os

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole
from shared.database.session import get_db
from shared.research.decompose import DEFAULT_MIN_ANCHOR_SCORE
from shared.research.deliverable import render_deliverable
from shared.research.export import to_markdown
from shared.research.gate import DEFAULT_GAP_THRESHOLD
from shared.research.orchestrator import answer_question
from shared.research.pilot import run_pilot

router = APIRouter()


class ResearchQuery(BaseModel):
    question: str = Field(..., min_length=5, description="Pregunta libre del comprador")
    gap_threshold: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Umbral de brecha para el gate (default 0.40 del spec §3.4)")
    per_q_k: int = Field(4, ge=1, le=10, description="Pasajes por sub-pregunta")
    min_anchor_score: Optional[float] = Field(
        None, ge=0.0,
        description="Umbral de ancla léxica (default calibrado; marginal → brecha)")


@router.post("")
async def run_research(
    body: ResearchQuery,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Responde una pregunta libre con procedencia honesta + gate de publicación."""
    answer = await answer_question(
        body.question, db=db,
        gap_threshold=body.gap_threshold if body.gap_threshold is not None
        else DEFAULT_GAP_THRESHOLD,
        per_q_k=body.per_q_k,
        min_anchor_score=body.min_anchor_score if body.min_anchor_score is not None
        else DEFAULT_MIN_ANCHOR_SCORE,
    )
    result = answer.to_dict()
    result["markdown"] = to_markdown(answer)   # documento con anatomía REPORT_STANDARD
    return result


class DeliverableRequest(BaseModel):
    question: str = Field(..., min_length=5)
    fmt: str = Field("pdf", pattern="^(pdf|docx)$", description="pdf | docx")
    gap_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    min_anchor_score: Optional[float] = Field(None, ge=0.0)
    watermark: Optional[str] = Field(None, description="Marca de agua; vacío = 'BORRADOR'")


@router.post("/deliverable")
async def research_deliverable(
    body: DeliverableRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FileResponse:
    """Fase 5: la respuesta del motor como entregable de marca (PDF/Word) — el borrador
    anclado a procedencia que acelera el DD Full/Deep Dive. Reusa el pipeline branded."""
    answer = await answer_question(
        body.question, db=db,
        gap_threshold=body.gap_threshold if body.gap_threshold is not None
        else DEFAULT_GAP_THRESHOLD,
        min_anchor_score=body.min_anchor_score if body.min_anchor_score is not None
        else DEFAULT_MIN_ANCHOR_SCORE,
    )
    kw = {"watermark": body.watermark} if body.watermark is not None else {}
    path = render_deliverable(answer, fmt=body.fmt, **kw)
    media = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"
             if body.fmt == "docx" else "application/pdf")
    return FileResponse(path, media_type=media, filename=os.path.basename(path))


class PilotRequest(BaseModel):
    questions: List[str] = Field(..., min_length=1, max_length=25,
                                 description="Preguntas reales del piloto (Fase 2)")
    gap_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)


@router.post("/pilot")
async def run_research_pilot(
    body: PilotRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    """Instrumentación del piloto manual (Fase 2, admin): corre el lote de preguntas y
    devuelve métricas de cobertura por pregunta + markdown. Las columnas de horas/costo
    las completa el analista (no se fabrican)."""
    report = await run_pilot(
        body.questions, db=db,
        gap_threshold=body.gap_threshold if body.gap_threshold is not None
        else DEFAULT_GAP_THRESHOLD,
    )
    result = report.to_dict()
    result["markdown"] = report.to_markdown()
    return result


@router.get("/packaging")
def research_packaging(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    """Fase 6: estado comercial del tier de research custom, LEÍDO del tarifario. Sin
    tarifa vigente para su SKU ``special:research-custom`` → inactivo. El precio vive en
    el tarifario (Tariff), no hardcodeado (§6)."""
    from shared.research.packaging import packaging_status
    return packaging_status(db)


class SetPriceRequest(BaseModel):
    amount_usd: float = Field(..., gt=0, description="Precio provisional por encargo (US$)")


@router.post("/packaging/price")
def set_research_price(
    body: SetPriceRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    """Publica el precio PROVISIONAL del tier en el tarifario (una fila Tariff). El monto
    lo decide el dueño; queda marcado provisional para recalibrar con el piloto (Fase 5).
    El precio vive en el tarifario como cualquier SKU — editable después desde /admin/pagos."""
    from shared.research.packaging import packaging_status, set_provisional_price
    set_provisional_price(db, body.amount_usd, created_by=getattr(admin, "id", None))
    return packaging_status(db)
