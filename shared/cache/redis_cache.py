"""Cliente Redis compartido para caché — lazy, opcional y con breaker.

Diseño:
- Lazy singleton sobre ``settings.REDIS_URL`` (vacío = deshabilitado, dev funciona
  sin Redis igual que hoy).
- Timeouts cortos (1s): una caché lenta es peor que no tener caché.
- Breaker simple: tras un fallo de conexión se deja de intentar por
  ``_BREAKER_SECONDS`` — así un Redis caído no agrega 1s de latencia a CADA
  generación de narrativa, solo al primer intento de la ventana.
- Best-effort en todas las operaciones: cualquier excepción se loguea y devuelve
  None/no-op. La caché nunca rompe la request.
"""
import logging
import threading
import time
from typing import Optional

from shared.config.settings import settings

logger = logging.getLogger("sdq.cache.redis")

_BREAKER_SECONDS = 30.0

_lock = threading.Lock()
_client = None
_client_failed_at: float = 0.0


def _get_client():
    """Cliente Redis o None (sin REDIS_URL, import fallido, o breaker abierto)."""
    global _client, _client_failed_at
    if not settings.REDIS_URL:
        return None
    if _client is not None:
        return _client
    if time.time() - _client_failed_at < _BREAKER_SECONDS:
        return None
    with _lock:
        if _client is not None:
            return _client
        try:
            import redis

            client = redis.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=1,
                socket_timeout=1,
                decode_responses=True,
            )
            client.ping()
            _client = client
            return _client
        except Exception as e:  # noqa: BLE001 — caché opcional; jamás rompe la request
            _client_failed_at = time.time()
            logger.warning("Redis de caché no disponible (%s); se opera solo con L1.", e)
            return None


def _drop_client():
    """Descarta el cliente tras un error de operación y abre el breaker."""
    global _client, _client_failed_at
    with _lock:
        _client = None
        _client_failed_at = time.time()


def cache_get(key: str) -> Optional[str]:
    client = _get_client()
    if client is None:
        return None
    try:
        return client.get(key)
    except Exception as e:  # noqa: BLE001
        logger.warning("cache_get(%s) falló (%s); breaker abierto.", key, e)
        _drop_client()
        return None


def cache_set(key: str, value: str, ttl_seconds: int) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        client.set(key, value, ex=max(1, int(ttl_seconds)))
    except Exception as e:  # noqa: BLE001
        logger.warning("cache_set(%s) falló (%s); breaker abierto.", key, e)
        _drop_client()


def cache_incr_float(key: str, amount: float, ttl_seconds: int) -> Optional[float]:
    """INCRBYFLOAT atómico con TTL (para contadores compartidos, p. ej. gasto LLM).

    Devuelve el total acumulado, o None si Redis no está disponible (el caller
    decide su fallback — típicamente un contador in-memory por worker)."""
    client = _get_client()
    if client is None:
        return None
    try:
        total = client.incrbyfloat(key, amount)
        # TTL solo si no tiene (no resetear la ventana en cada incremento)
        if client.ttl(key) < 0:
            client.expire(key, max(1, int(ttl_seconds)))
        return float(total)
    except Exception as e:  # noqa: BLE001
        logger.warning("cache_incr_float(%s) falló (%s); breaker abierto.", key, e)
        _drop_client()
        return None
