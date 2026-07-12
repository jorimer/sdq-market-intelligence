"""RAG knowledge layer — recuperación léxica sobre corpus propio + Data Registry.

Motor de Research Custom · Fase 3 (docs/SPEC_MOTOR_RESEARCH_CUSTOM.md §3.2). Reemplaza
el stub diferido: ``retrieve`` ahora recupera de verdad sobre material de derechos
claros (doctrina versionada, metodología propia) y el Data Registry vivo, con
procedencia adjunta en cada pasaje. Alcance acotado: sin web abierta ni scraping en
vivo (§7) — una fuente externa nueva sigue el flujo ``shared/source_intel``.
"""
from shared.knowledge.ingest import build_index, build_passages
from shared.knowledge.models import Passage
from shared.knowledge.retrieve import retrieve

__all__ = ["retrieve", "build_index", "build_passages", "Passage"]
