from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.config.settings import settings
from shared.database.paths import ensure_sqlite_directory

# SQLite no crea el directorio del fichero: sin esto, un árbol recién clonado (donde
# ``data/`` está gitignorado) falla en TODA conexión con «unable to open database file»
# —incluido el readiness, que responde 503. Ver shared/database/paths.py.
ensure_sqlite_directory(settings.DATABASE_URL)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=(
        {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
    ),
    echo=settings.DEBUG,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
