"""Cuánto ocupa la base y quién la ocupa — medido, no estimado.

Existe por un aviso de memoria en el Postgres de producción (2026-08-21). La pregunta
«¿por qué crece?» se puede contestar de dos maneras: razonando sobre qué tablas parecen
grandes, o preguntándole al motor. La primera produce una conjetura que suena a diagnóstico;
la segunda produce un número. Este módulo hace la segunda.

Importa especialmente acá porque la plataforma tiene tres tablas que crecen SIN retención y
por diseño: la caché de narrativas (``product_report_cache``, explícitamente sin TTL — un
informe cacheado sirve hasta que cambie el dato que lo generó), el registro de gasto del
modelo (``llm_calls``, que es evidencia de auditoría) y el historial de operaciones
(``operation_runs``). Ninguna se purga sola, y esa decisión está bien tomada: borrar
evidencia por espacio es una decisión de negocio, no de infraestructura. Pero para TOMARLA
hay que ver los tamaños.

Solo Postgres. En SQLite (desarrollo) se declara que no aplica en vez de devolver ceros: un
cero se lee como «no ocupa nada» y sería mentira.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from shared.config.settings import settings
from shared.database.session import engine

logger = logging.getLogger("sdq.database.huella")

#: Cuántas tablas listar. Las grandes son pocas; el resto es ruido en una pantalla.
_TOP = 15

#: Tablas que crecen sin retención por diseño, con el motivo. Se marcan en la respuesta para
#: que quien mire el tamaño sepa cuáles crecen para siempre a propósito y cuáles no deberían.
SIN_RETENCION: Dict[str, str] = {
    "product_report_cache": "caché de narrativas sin TTL: un informe sirve hasta que cambie "
                            "su dato de origen",
    "llm_calls": "registro de gasto del modelo: es la evidencia de a quién cobrarle cada "
                 "llamada",
    "operation_runs": "historial de operaciones: es la auditoría de qué corrió y cuándo",
}

_SQL_TABLAS = text("""
    SELECT relname AS tabla,
           pg_total_relation_size(c.oid) AS bytes_total,
           pg_relation_size(c.oid)       AS bytes_datos,
           n_live_tup                    AS filas_vivas,
           n_dead_tup                    AS filas_muertas
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
     WHERE c.relkind = 'r' AND n.nspname = 'public'
     ORDER BY pg_total_relation_size(c.oid) DESC
     LIMIT :tope
""")


def _es_postgres() -> bool:
    return settings.DATABASE_URL.startswith(("postgresql", "postgres://"))


def estado_del_pool() -> Dict[str, Any]:
    """Conexiones de ESTE proceso, y el techo que puede abrir.

    La salvedad viaja con el número: cada worker de uvicorn tiene su propio pool, y el
    servicio de Celery el suyo. Lo que ve Postgres es la SUMA. Un panel que mostrara solo
    estas cifras se leería como el total y subestimaría el consumo real por un factor igual
    a la cantidad de procesos.
    """
    pool = engine.pool
    def _n(nombre: str):
        fn = getattr(pool, nombre, None)
        try:
            return fn() if callable(fn) else None
        except Exception:  # noqa: BLE001 — un contador no rompe la pantalla
            return None
    return {
        "en_uso": _n("checkedout"),
        "ociosas_en_pool": _n("checkedin"),
        "desbordadas": _n("overflow"),
        "techo_por_proceso": settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW,
        "alcance": "Solo ESTE proceso. Cada worker web y el worker de Celery abren su propio "
                   "pool; lo que ve Postgres es la suma de todos.",
    }


def huella_de_la_base(db: Session) -> Dict[str, Any]:
    """Tamaño de la base y de sus tablas más grandes, con el estado del pool de conexiones.

    Devuelve ``aplica=False`` en SQLite en vez de ceros: «no se puede medir acá» y «no ocupa
    nada» son cosas distintas.
    """
    if not _es_postgres():
        return {
            "aplica": False,
            "motivo": "La huella se mide sobre PostgreSQL; este entorno corre SQLite.",
            "conexiones": estado_del_pool(),
        }
    try:
        total = db.execute(text("SELECT pg_database_size(current_database())")).scalar()
        filas = db.execute(_SQL_TABLAS, {"tope": _TOP}).mappings().all()
    except Exception as e:  # noqa: BLE001 — un panel de diagnóstico no puede tumbar la consola
        logger.warning("No se pudo medir la huella de la base: %s", e)
        db.rollback()
        return {"aplica": True, "error": f"No se pudo medir: {e}",
                "conexiones": estado_del_pool()}

    tablas: List[Dict[str, Any]] = []
    for f in filas:
        nombre = f["tabla"]
        tablas.append({
            "tabla": nombre,
            "mb_total": round((f["bytes_total"] or 0) / 1_048_576, 2),
            "mb_datos": round((f["bytes_datos"] or 0) / 1_048_576, 2),
            "filas_vivas": f["filas_vivas"],
            # Filas muertas altas = autovacuum atrasado, que es trabajo y memoria del motor.
            "filas_muertas": f["filas_muertas"],
            "sin_retencion": SIN_RETENCION.get(nombre),
        })
    return {
        "aplica": True,
        "mb_base_completa": round((total or 0) / 1_048_576, 2),
        "tablas": tablas,
        "conexiones": estado_del_pool(),
        "nota": "Las tablas marcadas con «sin_retencion» crecen para siempre A PROPÓSITO: son "
                "caché servible y evidencia de auditoría. Purgarlas es una decisión de "
                "negocio con estos números a la vista, no una tarea de mantenimiento.",
    }
