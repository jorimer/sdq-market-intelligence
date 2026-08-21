"""Caché compartida multi-worker sobre Redis (best-effort).

Las cachés in-memory del motor de narrativa y del router semántico viven UNA COPIA
POR WORKER uvicorn: un hit en el worker A no le sirve al worker B, y cada deploy las
vacía. Este módulo agrega la capa compartida: Redis (el mismo de Celery/health, ya
en prod) como L2, con la caché in-memory como L1. Todo es best-effort — sin
REDIS_URL, o con Redis caído, las operaciones degradan a no-op y el sistema queda
exactamente como antes (L1 por worker). La caché JAMÁS debe tumbar una request.
"""
from shared.cache.redis_cache import (
    cache_disponible,
    cache_get,
    cache_incr_float,
    cache_set,
)

__all__ = ["cache_get", "cache_set", "cache_incr_float", "cache_disponible"]
