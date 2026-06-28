"""Servicio del tablero de Inteligencia de Fuentes — CRUD + ciclo de vida.

Fundación (Increment 1): alta/lista/estado de sugerencias. La evaluación IA (Increment
2), el agente que las puebla (Increment 3) y el andamiaje de integración (Increment 4)
se montan encima sin tocar este contrato.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.source_intel.models import (
    KINDS,
    ORIGIN_MANUAL,
    ORIGINS,
    STATUSES,
    STATUS_PROPOSED,
    SourceSuggestion,
)


class SuggestionError(ValueError):
    """Entrada inválida (kind/status desconocido, sugerencia inexistente)."""


def _serialize(s: SourceSuggestion) -> Dict[str, Any]:
    return {
        "id": s.id,
        "kind": s.kind,
        "title": s.title,
        "description": s.description or "",
        "origin": s.origin,
        "proposed_by": s.proposed_by,
        "target_axis": s.target_axis,
        "target_gate": s.target_gate,
        "status": s.status,
        "evaluation": s.evaluation,
        "decision_note": s.decision_note,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def create_suggestion(
    db: Session, *, kind: str, title: str, description: str = "",
    origin: str = ORIGIN_MANUAL, proposed_by: Optional[str] = None,
    target_axis: Optional[str] = None, target_gate: Optional[str] = None,
) -> Dict[str, Any]:
    """Crea una sugerencia (manual o del agente). Valida ``kind`` y campos mínimos."""
    if kind not in KINDS:
        raise SuggestionError(f"Tipo inválido '{kind}'. Use: {', '.join(KINDS)}.")
    if not (title or "").strip():
        raise SuggestionError("El título es obligatorio.")
    if origin not in ORIGINS:
        raise SuggestionError(f"Origen inválido '{origin}'.")
    row = SourceSuggestion(
        kind=kind, title=title.strip(), description=(description or "").strip(),
        origin=origin, proposed_by=proposed_by, target_axis=target_axis,
        target_gate=target_gate, status=STATUS_PROPOSED)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


def list_suggestions(db: Session, *, status: Optional[str] = None,
                     axis: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lista las sugerencias (más recientes primero), filtrables por estado y eje."""
    q = db.query(SourceSuggestion)
    if status:
        q = q.filter(SourceSuggestion.status == status)
    if axis:
        q = q.filter(SourceSuggestion.target_axis == axis)
    rows = q.order_by(SourceSuggestion.created_at.desc()).all()
    return [_serialize(r) for r in rows]


def get_suggestion(db: Session, suggestion_id: str) -> Dict[str, Any]:
    row = db.query(SourceSuggestion).filter_by(id=suggestion_id).one_or_none()
    if row is None:
        raise SuggestionError("Sugerencia no encontrada.")
    return _serialize(row)


def set_status(db: Session, suggestion_id: str, status: str,
               decision_note: Optional[str] = None) -> Dict[str, Any]:
    """Mueve la sugerencia de estado (el dueño gestiona el flujo). Valida el estado."""
    if status not in STATUSES:
        raise SuggestionError(f"Estado inválido '{status}'. Use: {', '.join(STATUSES)}.")
    row = db.query(SourceSuggestion).filter_by(id=suggestion_id).one_or_none()
    if row is None:
        raise SuggestionError("Sugerencia no encontrada.")
    row.status = status
    if decision_note is not None:
        row.decision_note = decision_note.strip() or None
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _serialize(row)


def evaluate(db: Session, suggestion_id: str) -> Dict[str, Any]:
    """Evalúa la sugerencia con IA (o heurística) y persiste el resultado + estado.

    Mueve a ``evaluated`` si venía de un estado temprano (proposed/evaluating); no
    pisa una decisión ya tomada (approved/rejected/…)."""
    from shared.source_intel.evaluator import evaluate_suggestion
    from shared.source_intel.models import (
        STATUS_EVALUATED,
        STATUS_EVALUATING,
        STATUS_PROPOSED,
    )

    row = db.query(SourceSuggestion).filter_by(id=suggestion_id).one_or_none()
    if row is None:
        raise SuggestionError("Sugerencia no encontrada.")
    row.evaluation = evaluate_suggestion(db, _serialize(row))
    if row.status in (STATUS_PROPOSED, STATUS_EVALUATING):
        row.status = STATUS_EVALUATED
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _serialize(row)


def delete_suggestion(db: Session, suggestion_id: str) -> bool:
    row = db.query(SourceSuggestion).filter_by(id=suggestion_id).one_or_none()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def board_summary(db: Session) -> Dict[str, int]:
    """Conteo por estado (para el encabezado del tablero)."""
    out = {st: 0 for st in STATUSES}
    for r in db.query(SourceSuggestion).all():
        out[r.status] = out.get(r.status, 0) + 1
    return out
