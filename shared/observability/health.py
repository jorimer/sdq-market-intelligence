"""Health checks profundos: la readiness toca las dependencias reales (DB, y Redis
si está configurado) para que una réplica que no puede servir NO se reporte "sana".

- ``liveness()``: el proceso está vivo. Estático, no toca dependencias — no debe
  fallar por un blip de la DB (evita tormentas de reinicio).
- ``readiness()``: ¿puede esta réplica atender tráfico? Falla (503) si una
  dependencia *configurada* está caída. Redis solo se chequea si REDIS_URL está
  seteado (es opcional en este despliegue).
"""
import logging
import time
from typing import Any, Dict, Tuple

from sqlalchemy import text

from shared.config.settings import settings
from shared.database.session import SessionLocal

logger = logging.getLogger("sdq.health")

APP_VERSION = "1.0.0"


def _check_db() -> Tuple[bool, Dict[str, Any]]:
    start = time.monotonic()
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        return True, {"ok": True, "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as e:  # noqa: BLE001 — reportamos el fallo, no lo propagamos
        logger.warning("health: DB no disponible: %s", e)
        return False, {"ok": False, "error": str(e)[:200]}


def _check_redis() -> Tuple[bool, Dict[str, Any]]:
    url = (settings.REDIS_URL or "").strip()
    if not url:
        return True, {"ok": True, "configured": False}  # opcional → no bloquea
    start = time.monotonic()
    try:
        import redis
        client = redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        return True, {"ok": True, "configured": True,
                      "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as e:  # noqa: BLE001
        logger.warning("health: Redis no disponible: %s", e)
        return False, {"ok": False, "configured": True, "error": str(e)[:200]}


def liveness() -> Dict[str, Any]:
    return {"status": "ok", "platform": "SDQ Market Intelligence", "version": APP_VERSION}


def readiness() -> Tuple[bool, Dict[str, Any]]:
    """(healthy, payload). healthy=False → el endpoint responde 503."""
    db_ok, db_detail = _check_db()
    redis_ok, redis_detail = _check_redis()
    healthy = db_ok and redis_ok
    return healthy, {
        "status": "ok" if healthy else "degraded",
        "platform": "SDQ Market Intelligence",
        "version": APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "checks": {"database": db_detail, "redis": redis_detail},
    }
