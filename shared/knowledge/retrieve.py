"""RAG retrieval — recuperación léxica sobre el corpus propio + el Data Registry.

Motor de Research Custom · Fase 3 (docs/SPEC_MOTOR_RESEARCH_CUSTOM.md §3.2).

Reemplaza el stub que devolvía ``[]``. Contrato preservado para los llamadores
existentes (el motor de narrativa llama ``retrieve(query, top_k)``): sigue devolviendo
una lista de pasajes ``{"text", "source", "score", ...}``. Ahora cada pasaje trae
además ``kind``/``ref``/``license`` para que el orquestador (Fase 4) pueda decidir si
la evidencia es dato real, doctrina o metodología —y anclar la procedencia (§4).

Alcance (§7): NO web abierta, NO scraping en vivo. Solo material de derechos claros.
Una consulta sin resultados NO es un error: es la señal honesta de brecha.
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.knowledge.ingest import build_index

logger = logging.getLogger("sdq.knowledge")


def retrieve(query: str, top_k: int = 5, *,
             db: Optional[Session] = None,
             include_registry: bool = True,
             min_score: float = 0.0) -> List[Dict[str, Any]]:
    """Hasta *top_k* pasajes relevantes para *query*, cada uno con su procedencia.

    ``db`` (opcional): si se pasa una sesión, el índice incluye el Data Registry vivo
    (qué dato real existe hoy) además del corpus documental. Sin ``db`` recupera solo
    sobre el corpus estático (doctrina + metodología). Lista vacía = sin evidencia
    (brecha declarada), nunca un relleno inventado.
    """
    if not (query or "").strip():
        return []
    index = build_index(db=db, include_registry=include_registry)
    hits = index.search(query, top_k=top_k, min_score=min_score)
    logger.debug("knowledge.retrieve(query=%r, top_k=%d) -> %d pasajes",
                 query, top_k, len(hits))
    return [p.as_result(score) for p, score in hits]
