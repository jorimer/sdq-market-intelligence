"""Health checks profundos: la readiness toca las dependencias reales (DB, y Redis
si está configurado) para que una réplica que no puede servir NO se reporte "sana".

- ``liveness()``: el proceso está vivo. Estático, no toca dependencias — no debe
  fallar por un blip de la DB (evita tormentas de reinicio).
- ``readiness()``: ¿puede esta réplica atender tráfico? Falla (503) si una
  dependencia *configurada* está caída. Redis solo se chequea si REDIS_URL está
  seteado (es opcional en este despliegue).
"""
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import text

from shared.config.settings import settings
from shared.database.session import SessionLocal

logger = logging.getLogger("sdq.health")

APP_VERSION = "1.0.0"

#: Variables que la plataforma de despliegue inyecta con el commit desplegado. Se prueban
#: en orden: la primera es la de Railway, que es donde corre hoy; las otras dos permiten
#: sellar la imagen a mano (``docker build --build-arg``) sin tocar este código.
_VARS_COMMIT = ("RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT", "SOURCE_COMMIT")
_VARS_RAMA = ("RAILWAY_GIT_BRANCH", "GIT_BRANCH")


def _primera(nombres: Tuple[str, ...]) -> Optional[str]:
    for n in nombres:
        v = (os.environ.get(n) or "").strip()
        if v:
            return v
    return None


def deployment_stamp() -> Dict[str, Any]:
    """QUÉ COMMIT está sirviendo esta réplica.

    Existe por un fallo concreto: un despliegue falló, la plataforma dejó corriendo el
    proceso ANTERIOR, y ``/health`` siguió respondiendo `status: ok` — porque el proceso
    sano era el viejo. Se estuvo verificando producción ochenta minutos contra un cambio
    que nunca se desplegó. «Sano» y «sano y viejo» eran indistinguibles desde afuera.

    Ausente se declara `None`, nunca `"unknown"` ni `"dev"`: un valor inventado acá es peor
    que ninguno, porque el que lo lea creerá que verificó el commit y no lo hizo.
    """
    commit = _primera(_VARS_COMMIT)
    return {
        "commit": commit,
        # El corto es para leerlo de un vistazo y cotejarlo con `git log --oneline`.
        "commit_short": commit[:7] if commit else None,
        "branch": _primera(_VARS_RAMA),
        # Identifica el despliegue en la consola de la plataforma: es el eslabón que faltaba
        # entre «prod responde raro» y la fila que dice FAILED.
        "deployment_id": _primera(("RAILWAY_DEPLOYMENT_ID",)),
        "nota": (None if commit else
                 "Sin sello de despliegue: el entorno no inyecta el commit. NO se puede "
                 "afirmar qué versión está sirviendo esta réplica."),
    }


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
    # El sello va TAMBIÉN acá: es la sonda más barata y la que no toca dependencias, así que
    # es la que se consulta para preguntar «¿qué está corriendo?» sin cargar la DB.
    return {"status": "ok", "platform": "SDQ Market Intelligence", "version": APP_VERSION,
            "deployment": deployment_stamp()}


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
        "deployment": deployment_stamp(),
        "checks": {"database": db_detail, "redis": redis_detail},
    }
