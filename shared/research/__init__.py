"""Motor de Research Custom — orquestador de pregunta libre + gate de honestidad.

docs/SPEC_MOTOR_RESEARCH_CUSTOM.md §3.3/§3.4/§4 (Fase 4).

Toma una pregunta libre de un comprador (no un template fijo) y produce una respuesta
con la misma anatomía y el mismo estándar de honestidad de procedencia que el resto del
catálogo: toda sub-afirmación ancla a dato real, rúbrica declarada o brecha declarada —
nunca se rellena con conocimiento paramétrico del modelo disfrazado de dato.

Piezas:
- ``decompose``    — parte la pregunta en sub-preguntas mapeadas a ejes/indicadores.
- ``orchestrator`` — recupera evidencia (con procedencia) por sub-pregunta y ensambla.
- ``gate``         — regla dura: si el cuerpo sin ancla supera el umbral → scoping report.
"""
from shared.research.models import (
    Evidence,
    ResearchAnswer,
    SubQuestion,
)
from shared.research.orchestrator import answer_question

__all__ = ["answer_question", "ResearchAnswer", "SubQuestion", "Evidence"]
