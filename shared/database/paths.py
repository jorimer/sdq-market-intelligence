"""El DIRECTORIO del fichero SQLite: crearlo antes de abrir la conexión.

SQLite crea el *fichero* de la base si no existe, pero **no su directorio**: contra
``sqlite:///./data/sdq_market_intel.db`` —el valor por defecto de ``DATABASE_URL``— en un
árbol recién clonado (o un worktree nuevo, donde ``data/`` está gitignorado y por lo tanto
no viaja) toda conexión muere con «unable to open database file». No es un error de
configuración: es la configuración por defecto del repo contra un checkout limpio.

**El caso que lo motivó.** ``test_health_check`` fallaba de forma aparentemente aleatoria en
la suite completa: el readiness toca la base REAL —no la in-memory que los tests inyectan
por ``get_db``, porque comprobar una base falsa no comprueba nada— y sin ``data/`` devolvía
503. Se veía intermitente porque se curaba solo: el test es el número 25 de la suite y el
40 (``test_report_generate``) crea ``data/reports`` al escribir un PDF. Primera corrida en
un árbol nuevo: falla. Todas las siguientes: pasan. Nunca fue orden aleatorio ni una carrera.

En producción la base es Postgres y esta ruta no aplica; el precio lo paga el entorno de
desarrollo, donde un clon nuevo levanta un servidor que responde 503 en ``/api/v1/health``
y 500 en todo lo que toque la base, con un error que no nombra la causa (el directorio).
"""
import logging
import os

from sqlalchemy.engine import make_url

logger = logging.getLogger("sdq.database")


def ensure_sqlite_directory(url: str) -> None:
    """Crea el directorio del fichero SQLite de ``url``. No-op para el resto.

    Se llama ANTES de construir el engine, en cada sitio que construye uno (la app y
    Alembic tienen el suyo). Silencioso a propósito en los dos casos en que no puede
    hacer nada: una URL que no parsea la reporta ``create_engine`` con su mensaje
    canónico, y un directorio que no se puede crear degrada al error de conexión de
    siempre —que el health check ya reporta— en vez de tumbar el import del módulo.
    """
    try:
        parsed = make_url(url)
    except Exception:  # noqa: BLE001 — el error de URL lo reporta create_engine
        return
    if not parsed.drivername.startswith("sqlite"):
        return
    # ``sqlite://`` (memoria) deja database en None; ``sqlite:///:memory:`` lo deja literal.
    if not parsed.database or parsed.database == ":memory:":
        return
    directorio = os.path.dirname(os.path.abspath(parsed.database))
    try:
        os.makedirs(directorio, exist_ok=True)
    except OSError as e:  # noqa: PERF203 — degradar, no romper el import
        logger.warning("No se pudo crear el directorio de la base SQLite %s: %s", directorio, e)
