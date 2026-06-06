"""RAG knowledge layer (DEFERRED — Fase 0 ships a stub only).

The full pipeline (ingest with license check, rights-cleared corpus, vector
index, retrieve) lands in a later phase.  For now :func:`retrieve` returns an
empty result so ``shared/narrative`` can call it without breaking.
"""
from shared.knowledge.retrieve import retrieve

__all__ = ["retrieve"]
