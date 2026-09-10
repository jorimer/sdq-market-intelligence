from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.config.settings import settings
from shared.database.paths import ensure_sqlite_directory

# SQLite no crea el directorio del fichero: sin esto, un árbol recién clonado (donde
# ``data/`` está gitignorado) falla en TODA conexión con «unable to open database file»
# —incluido el readiness, que responde 503. Ver shared/database/paths.py.
ensure_sqlite_directory(settings.DATABASE_URL)

_es_sqlite = "sqlite" in settings.DATABASE_URL

# El pool se configura SOLO en Postgres: en SQLite (desarrollo) el pooling es otro y estos
# parámetros no aplican. Ver `DB_POOL_SIZE` en shared/config/settings.py para el porqué de
# cada número — resumido: el techo real es (pool + overflow) × cantidad de procesos, y cada
# conexión es un backend de Postgres con su propia memoria.
_pool_kwargs = {} if _es_sqlite else {
    "pool_size": settings.DB_POOL_SIZE,
    "max_overflow": settings.DB_MAX_OVERFLOW,
    "pool_recycle": settings.DB_POOL_RECYCLE_SECONDS,
    "pool_pre_ping": True,
}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if _es_sqlite else {},
    echo=settings.DEBUG,
    **_pool_kwargs,
)

# ── SQLite: WAL, para que una SEGUNDA conexión pueda escribir ────────────────────────
#
# En el modo por defecto (`journal_mode=delete`), commitear exige subir a EXCLUSIVE, y eso no
# se puede mientras otra conexión tiene la base tomada dentro de una transacción abierta —
# aunque solo la esté LEYENDO. WAL admite un escritor concurrente con lectores; dos
# ESCRITORES siguen excluyéndose, y está bien así.
#
# Sin esto se rompe un patrón que la plataforma usa a propósito en su instrumentación: el
# registro de gasto del modelo (`llm_ledger.record_call`) y el contador de herramientas
# (`uso_de_herramientas.registrar_uso`) abren su PROPIA sesión corta, para que un fallo
# posterior de la ruta —y la reversión de su transacción— no borre lo que ya ocurrió y ya se
# pagó.
#
# Medido, no supuesto: contra `POST /api/v1/research`, seis corridas por HTTP dejaban UNA
# fila del contador —las cinco perdidas avisaban por el log— y con estos PRAGMA dejan las
# seis. No es un detalle de rendimiento: un contador que subcuenta el 83 % enseña a
# desconfiar del panel, y eso es peor que no tenerlo.
#
# Solo aplica a SQLite (desarrollo). PostgreSQL —producción— no tiene este problema: dos
# conexiones escriben a la vez sin bloquearse. `busy_timeout` acompaña al WAL para que una
# contención breve espere en vez de fallar.


def aplicar_pragmas_sqlite(dbapi_connection) -> None:
    """Los PRAGMA de toda conexión SQLite. Función con nombre y no un closure para que el
    test de regresión pueda ejercer ESTA misma, en vez de reimplementar el criterio al
    lado — dos implementaciones de la misma regla es cómo se cuela un falso verde."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


if _es_sqlite:
    from sqlalchemy import event

    event.listen(engine, "connect",
                 lambda dbapi_connection, _record: aplicar_pragmas_sqlite(dbapi_connection))


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
