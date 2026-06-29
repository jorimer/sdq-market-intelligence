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
    STATUS_APPROVED,
    STATUS_DEFERRED,
    STATUS_EVALUATED,
    STATUS_EVALUATING,
    STATUS_INTEGRATING,
    STATUS_PROPOSED,
    STATUSES,
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
        "integration_plan": s.integration_plan,
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


def scaffold(db: Session, suggestion_id: str) -> Dict[str, Any]:
    """Genera y persiste el plan de integración de una sugerencia (Increment 4). No
    construye nada — es una propuesta para que el dueño/dev ejecute. Si la sugerencia
    está APROBADA, andamiar el plan es la señal de que arranca la integración → la mueve
    a ``integrating`` (la app gestiona ese estado intermedio)."""
    from shared.source_intel.scaffolder import scaffold_plan

    row = db.query(SourceSuggestion).filter_by(id=suggestion_id).one_or_none()
    if row is None:
        raise SuggestionError("Sugerencia no encontrada.")
    row.integration_plan = scaffold_plan(db, _serialize(row))
    if row.status == STATUS_APPROVED:
        row.status = STATUS_INTEGRATING
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


def reflag_covered_suggestions(db: Session) -> List[str]:
    """Auto-difiere las sugerencias ABIERTAS cuyo eje ya tiene su gate de datos cubierto.

    El sistema marca (no rechaza): mueve a ``deferred`` con nota «ya cubierto» y estampa
    ``already_covered`` en la evaluación. Reversible — el dueño puede reactivar o rechazar.
    Idempotente: solo toca estados tempranos (proposed/evaluating/evaluated) con eje y g1
    en pleno. Devuelve los ids afectados. Ver ``coverage.coverage_status``."""
    from shared.source_intel.coverage import coverage_status

    open_statuses = (STATUS_PROPOSED, STATUS_EVALUATING, STATUS_EVALUATED)
    rows = db.query(SourceSuggestion).filter(
        SourceSuggestion.status.in_(open_statuses),
        SourceSuggestion.target_axis.isnot(None)).all()
    changed: List[str] = []
    for row in rows:
        cov = coverage_status(db, row.target_axis)
        if not cov["covered"]:
            continue
        ev = dict(row.evaluation or {})
        ev["already_covered"] = True
        ev["coverage_note"] = cov["note"]
        row.evaluation = ev                      # reasignar → SQLAlchemy marca el JSON sucio
        row.status = STATUS_DEFERRED
        row.decision_note = f"Auto-diferida: {cov['note']}"[:1000]
        row.updated_at = datetime.now(timezone.utc)
        changed.append(row.id)
    if changed:
        db.commit()
    return changed


def flag_covered_decided(db: Session) -> List[str]:
    """Marca (sin cambiar estado) las sugerencias APROBADAS/INTEGRANDO cuyo eje ya está
    cubierto, para que el tablero muestre el badge «brecha cubierta» y el dueño decida con
    un clic: integrada (la construyó) o diferir (quedó redundante por otra fuente).

    NO auto-avanza a ``integrated``: la cobertura es por eje, no prueba que ESTA fuente se
    integrara (el eje pudo cubrirse por otra) — marcar «integrada» sola sería un falso
    positivo. El sistema detecta y avisa; el dueño confirma el estado terminal. Devuelve
    los ids cuyo flag cambió (idempotente)."""
    from shared.source_intel.coverage import coverage_status

    decided = (STATUS_APPROVED, STATUS_INTEGRATING)
    rows = db.query(SourceSuggestion).filter(
        SourceSuggestion.status.in_(decided),
        SourceSuggestion.target_axis.isnot(None)).all()
    flagged: List[str] = []
    for row in rows:
        cov = coverage_status(db, row.target_axis)
        ev = dict(row.evaluation or {})
        was = bool(ev.get("already_covered"))
        if cov["covered"] == was:
            continue                              # sin cambio → idempotente
        ev["already_covered"] = cov["covered"]
        if cov["covered"]:
            ev["coverage_note"] = cov["note"]
        else:
            ev.pop("coverage_note", None)         # el eje se reabrió → limpiar
        row.evaluation = ev
        row.updated_at = datetime.now(timezone.utc)
        flagged.append(row.id)
    if flagged:
        db.commit()
    return flagged
