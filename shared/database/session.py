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

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
