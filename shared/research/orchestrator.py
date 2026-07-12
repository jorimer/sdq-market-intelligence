"""Orquestador — de la pregunta libre a la respuesta con procedencia (§3.3).

Flujo: descompone la pregunta → recupera evidencia con procedencia por sub-pregunta →
aplica el gate de honestidad → ensambla la salida con la anatomía del REPORT_STANDARD
(informe completo) o un scoping report honesto (si el gate lo exige). Regla dura §4:
cada sub-afirmación se ancla SOLO con evidencia recuperada; lo que no la tiene se
declara brecha, nunca se rellena con conocimiento paramétrico del modelo.

Núcleo determinista (la garantía de honestidad no depende del LLM). El pulido de prosa
por el Cerebro es una extensión que se alimenta EXCLUSIVAMENTE de estos pasajes con
procedencia — nunca redacta sin evidencia adjunta.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from shared.registry.signals import GAP, REAL, RUBRIC
from shared.research.assemble import assemble_report_sections, assemble_scoping_sections
from shared.research.decompose import DEFAULT_MIN_ANCHOR_SCORE, decompose
from shared.research.gate import DEFAULT_GAP_THRESHOLD, evaluate_gate
from shared.research.models import (
    GATE_SCOPING,
    DeclaredGap,
    ResearchAnswer,
    SubQuestion,
)


def _collect_sources(sub_questions: List[SubQuestion]) -> List[str]:
    """Lineage único de la evidencia, dato real primero, preservando orden."""
    out: List[str] = []
    for want in (REAL, RUBRIC):
        for sq in sub_questions:
            for e in sq.evidence:
                if e.state == want and e.source and e.source not in out:
                    out.append(e.source)
    return out


def _collect_gaps(sub_questions: List[SubQuestion],
                  db: Optional[Session]) -> List[DeclaredGap]:
    """Brechas declaradas + (si existe) la fuente candidata del tablero source_intel."""
    gaps = [sq for sq in sub_questions if sq.state == GAP]
    if not gaps:
        return []
    candidates = _source_intel_candidates(db)
    return [DeclaredGap(sub_question=sq.text, note=sq.note,
                        candidate_source=candidates)
            for sq in gaps]


def _source_intel_candidates(db: Optional[Session]) -> Optional[str]:
    """Resumen best-effort de fuentes candidatas propuestas en el tablero source_intel
    (lado oferta). No mapea 1:1 a la brecha, pero orienta el siguiente paso honesto."""
    if db is None:
        return None
    try:
        from shared.source_intel.models import SourceSuggestion
        rows = (db.query(SourceSuggestion)
                .filter(SourceSuggestion.status.in_(("proposed", "evaluating", "evaluated")))
                .limit(5).all())
        names = [r.title for r in rows if getattr(r, "title", None)]
        return "; ".join(names) if names else None
    except Exception:  # noqa: BLE001 — tablero ausente en dev no debe romper la respuesta
        if db is not None:
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        return None


def answer_question(question: str, db: Optional[Session] = None, *,
                    gap_threshold: float = DEFAULT_GAP_THRESHOLD,
                    per_q_k: int = 4,
                    min_anchor_score: float = DEFAULT_MIN_ANCHOR_SCORE) -> ResearchAnswer:
    """Responde una pregunta libre con procedencia honesta y gate de publicación."""
    sub_questions = decompose(question, db=db, per_q_k=per_q_k,
                              min_anchor_score=min_anchor_score)
    gate, coverage_real, anchored_fraction = evaluate_gate(sub_questions, gap_threshold)
    sources = _collect_sources(sub_questions)
    gaps = _collect_gaps(sub_questions, db)

    if gate == GATE_SCOPING:
        sections = assemble_scoping_sections(question, sub_questions, sources, gaps,
                                             coverage_real, anchored_fraction)
    else:
        sections = assemble_report_sections(question, sub_questions, sources, gaps,
                                            coverage_real, anchored_fraction)

    return ResearchAnswer(
        question=question, gate=gate, coverage_real=coverage_real,
        anchored_fraction=anchored_fraction, sub_questions=sub_questions,
        sections=sections, sources=sources, gaps=gaps,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
