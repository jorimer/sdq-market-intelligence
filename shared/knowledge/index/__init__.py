"""Índice léxico del retrieval (BM25-lite, puro Python).

Motor de Research Custom · Fase 3 (docs/SPEC_MOTOR_RESEARCH_CUSTOM.md §3.2).

Deliberadamente SIN dependencias de vectores ni servicios externos: la §3.2 acota el
alcance a "recuperación estructurada", no búsqueda semántica sobre la web. BM25 sobre
el corpus propio + el Data Registry es determinista, corre igual en dev y prod, y deja
la puerta abierta a cambiar el motor por embeddings detrás del MISMO contrato sin tocar
a los llamadores.
"""
from shared.knowledge.index.bm25 import LexicalIndex, tokenize

__all__ = ["LexicalIndex", "tokenize"]
