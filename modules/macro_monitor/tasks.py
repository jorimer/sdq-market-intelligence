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
