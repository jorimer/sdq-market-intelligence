"""API del motor de research custom — ``/api/v1/research``.

Recibe una pregunta libre y devuelve la respuesta con procedencia + el gate de
publicación (informe completo o scoping report). Gateado a usuarios autenticados;
la entrega comercial por-tier (DD Full/Deep Dive) se cablea en la Fase 5.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole
from shared.database.session import get_db
from shared.research.decompose import DEFAULT_MIN_ANCHOR_SCORE
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
def run_research(
    body: ResearchQuery,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Responde una pregunta libre con procedencia honesta + gate de publicación."""
    answer = answer_question(
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


class PilotRequest(BaseModel):
    questions: List[str] = Field(..., min_length=1, max_length=25,
                                 description="Preguntas reales del piloto (Fase 2)")
    gap_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)


@router.post("/pilot")
def run_research_pilot(
    body: PilotRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    """Instrumentación del piloto manual (Fase 2, admin): corre el lote de preguntas y
    devuelve métricas de cobertura por pregunta + markdown. Las columnas de horas/costo
    las completa el analista (no se fabrican)."""
    report = run_pilot(
        body.questions, db=db,
        gap_threshold=body.gap_threshold if body.gap_threshold is not None
        else DEFAULT_GAP_THRESHOLD,
    )
    result = report.to_dict()
    result["markdown"] = report.to_markdown()
    return result
