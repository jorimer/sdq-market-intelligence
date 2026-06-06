"""RAG retrieval — stub.

Real implementation (vector search over a rights-cleared corpus) is deferred.
The contract is fixed now so callers (narrative engine) can depend on it:
``retrieve`` returns a list of passages, each ``{"text", "source", "score"}``.
"""
import logging
from typing import Dict, List

logger = logging.getLogger("sdq.knowledge")


def retrieve(query: str, top_k: int = 5) -> List[Dict[str, str]]:
    """Return up to *top_k* relevant passages for *query* (empty until built)."""
    logger.debug("knowledge.retrieve stub called (query=%r, top_k=%d)", query, top_k)
    return []
