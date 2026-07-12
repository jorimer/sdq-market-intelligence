"""Descomposición de la pregunta libre en sub-preguntas + mapeo a evidencia.

Determinista por diseño (sin depender del LLM para la garantía de honestidad): parte
la pregunta en cláusulas sustantivas y, por cada una, recupera evidencia con
procedencia del corpus + Data Registry (`shared.knowledge.retrieve`). El estado de
ancla de la sub-pregunta = el mejor que su evidencia soporta (real > rúbrica > brecha).

Un splitter con LLM podría afinar la partición, pero NO cambia la regla dura: cada
sub-pregunta se ancla solo con lo que el retrieval devuelve; lo que no tiene evidencia
se marca brecha (§4).
"""
from __future__ import annotations

import re
from typing import List, Optional

from sqlalchemy.orm import Session

from shared.knowledge.retrieve import retrieve
from shared.registry.signals import GAP, REAL, RUBRIC
from shared.research.models import Evidence, SubQuestion

# Conectores de coordinación donde partir (además de . ? ; y saltos de línea).
_CONNECTORS = re.compile(
    r"\s*(?:[.?;\n]|,?\s+(?:y también|además|asimismo|y además|así como)\s+)\s*",
    re.IGNORECASE,
)
_MIN_TOKENS = 3   # una cláusula con menos que esto no es una sub-pregunta autónoma

# Umbral de ANCLA: un pasaje con score BM25 por debajo de esto NO ancla la sub-pregunta
# —es un roce léxico marginal, no evidencia. Sin él, una pregunta sobre un tópico/entidad
# ausente del corpus (p.ej. "precio del cacao en Marte") se colgaría de cualquier doc que
# comparta vocabulario genérico y fabricaría un ancla por omisión (el modo de fallo del §6).
# [Guessing] Default calibrado sobre el corpus actual (match legítimo ≳8, ruido ≲6); se
# re-calibra con las preguntas reales del piloto (Fase 2), como el umbral del gate (§3.4).
DEFAULT_MIN_ANCHOR_SCORE = 7.0


def split_question(text: str) -> List[str]:
    """Parte la pregunta en cláusulas sustantivas, deduplicando y preservando orden."""
    parts = _CONNECTORS.split(text or "")
    out: List[str] = []
    seen = set()
    for p in parts:
        clause = p.strip(" \t\r\n-·•")
        if len(clause.split()) < _MIN_TOKENS:
            continue
        key = clause.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(clause)
    # Si no se pudo partir (pregunta corta), la pregunta entera es una sub-pregunta.
    if not out and (text or "").strip():
        out.append(text.strip())
    return out


def _aggregate_state(evidence: List[Evidence]) -> str:
    """El mejor ancla que la evidencia soporta: real > rúbrica > brecha."""
    if any(e.state == REAL for e in evidence):
        return REAL
    if any(e.state == RUBRIC for e in evidence):
        return RUBRIC
    return GAP


def map_subquestion(text: str, db: Optional[Session], top_k: int = 4,
                    min_anchor_score: float = DEFAULT_MIN_ANCHOR_SCORE) -> SubQuestion:
    """Recupera evidencia para *text* y arma la ``SubQuestion`` con estado y ejes.

    Solo cuenta como evidencia (y como ancla) lo que supera ``min_anchor_score``: un
    roce léxico marginal no ancla — la sub-pregunta queda como brecha declarada (§4)."""
    hits = retrieve(text, top_k=top_k, db=db, min_score=min_anchor_score)
    evidence = [Evidence.from_passage(h) for h in hits]
    axes: List[str] = []
    for h in hits:
        sk = (h.get("meta") or {}).get("sector_key")
        if sk and sk not in axes:
            axes.append(sk)
    state = _aggregate_state(evidence)
    note = ("" if state != GAP else
            "Sin evidencia con procedencia en el corpus ni en el Data Registry: brecha "
            "declarada (no se completa con conocimiento general del modelo).")
    return SubQuestion(text=text, evidence=evidence, axes=axes, state=state, note=note)


def decompose(question: str, db: Optional[Session] = None, per_q_k: int = 4,
              min_anchor_score: float = DEFAULT_MIN_ANCHOR_SCORE) -> List[SubQuestion]:
    """Descompone la pregunta y mapea cada sub-pregunta a su evidencia con procedencia."""
    return [map_subquestion(clause, db, top_k=per_q_k, min_anchor_score=min_anchor_score)
            for clause in split_question(question)]
