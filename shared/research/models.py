"""Modelos del motor de research: sub-pregunta, evidencia y respuesta.

Los tres estados de ancla son los mismos del Data Registry y del REPORT_STANDARD
(`shared/registry/signals`): REAL · RUBRIC · GAP. Reusarlos —en vez de definir un
cuarto vocabulario— es lo que mantiene la trazabilidad de punta a punta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from shared.registry.signals import GAP, REAL, RUBRIC

# Decisión del gate de publicación (§3.4).
GATE_REPORT = "report"     # cobertura suficiente → informe completo
GATE_SCOPING = "scoping"   # demasiada brecha → scoping report honesto


@dataclass(frozen=True)
class Evidence:
    """Un pasaje recuperado con su procedencia — lo único con lo que el motor redacta."""

    text: str
    source: str
    kind: str          # doctrine | methodology | registry | bulletin
    state: str         # REAL | RUBRIC | GAP (derivado de la evidencia)
    score: float
    ref: str = ""
    license: str = ""

    @classmethod
    def from_passage(cls, r: Dict[str, Any]) -> "Evidence":
        """Construye desde un resultado de ``shared.knowledge.retrieve`` + su estado."""
        return cls(
            text=r.get("text", ""), source=r.get("source", ""),
            kind=r.get("kind", ""), state=_evidence_state(r),
            score=float(r.get("score", 0.0)), ref=r.get("ref", ""),
            license=r.get("license", ""),
        )


def _evidence_state(r: Dict[str, Any]) -> str:
    """Estado de ancla de un pasaje recuperado.

    - REAL   si es una señal del Data Registry con dato real (``meta.state == 'real'``).
    - RUBRIC si es doctrina / metodología / señal de rúbrica (hay método declarado,
             no necesariamente dato vivo).
    - GAP    en cualquier otro caso (no debería llegar aquí: sin evidencia no se crea).
    """
    meta = r.get("meta") or {}
    if r.get("kind") == "registry":
        return REAL if meta.get("state") == REAL else RUBRIC
    if r.get("kind") in ("doctrine", "methodology", "bulletin"):
        return RUBRIC
    return GAP


@dataclass
class SubQuestion:
    """Una sub-pregunta descompuesta, con su evidencia y estado de ancla."""

    text: str
    evidence: List[Evidence] = field(default_factory=list)
    axes: List[str] = field(default_factory=list)   # sector_keys mapeados
    state: str = GAP                                 # mejor ancla disponible
    note: str = ""

    @property
    def anchored(self) -> bool:
        """Anclada = tiene dato real O rúbrica declarada (no brecha). §3.4."""
        return self.state in (REAL, RUBRIC)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text, "state": self.state, "anchored": self.anchored,
            "axes": self.axes, "note": self.note,
            "evidence": [{"text": e.text, "source": e.source, "kind": e.kind,
                          "state": e.state, "score": e.score, "ref": e.ref}
                         for e in self.evidence],
        }


@dataclass
class DeclaredGap:
    """Una brecha declarada + (si existe) la fuente candidata que la cerraría."""

    sub_question: str
    note: str
    candidate_source: Optional[str] = None   # del tablero de source_intel, si hay

    def to_dict(self) -> Dict[str, Any]:
        return {"sub_question": self.sub_question, "note": self.note,
                "candidate_source": self.candidate_source}


@dataclass
class ResearchAnswer:
    """La respuesta del motor: gate + secciones + sub-preguntas + procedencia + brechas."""

    question: str
    gate: str                                        # GATE_REPORT | GATE_SCOPING
    coverage_real: float                             # fracción anclada a dato real
    anchored_fraction: float                         # fracción anclada (real o rúbrica)
    sub_questions: List[SubQuestion] = field(default_factory=list)
    sections: Dict[str, str] = field(default_factory=dict)
    sources: List[str] = field(default_factory=list)
    gaps: List[DeclaredGap] = field(default_factory=list)
    generated_at: str = ""

    @property
    def state_counts(self) -> Dict[str, int]:
        counts = {REAL: 0, RUBRIC: 0, GAP: 0}
        for sq in self.sub_questions:
            counts[sq.state] = counts.get(sq.state, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question, "gate": self.gate,
            "coverage_real": self.coverage_real,
            "anchored_fraction": self.anchored_fraction,
            "state_counts": self.state_counts,
            "sub_questions": [sq.to_dict() for sq in self.sub_questions],
            "sections": self.sections,
            "sources": self.sources,
            "gaps": [g.to_dict() for g in self.gaps],
            "generated_at": self.generated_at,
        }
