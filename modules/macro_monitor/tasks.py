"""Celery tasks for the macro_monitor module."""
from shared.tasks.celery_app import celery_app


@celery_app.task(name="macro.excel_batch", bind=True)
def excel_batch_task(self, **kwargs) -> dict:  # noqa: ARG001
    """Run the BCRD Excel batch over the catalog in the Celery worker."""
    from shared.database.session import SessionLocal
    from modules.macro_monitor.service import run_excel_batch

    db = SessionLocal()
    try:
        return run_excel_batch(db, **kwargs)
    finally:
        db.close()


@celery_app.task(name="macro.ingest_canonical", bind=True)
def ingest_canonical_task(self, persist: bool = False) -> dict:  # noqa: ARG001
    """Ingest only the canonical series in the Celery worker."""
    from shared.database.session import SessionLocal
    from modules.macro_monitor.service import ingest_canonical

    db = SessionLocal()
    try:
        return ingest_canonical(db, persist=persist)
    finally:
        db.close()
