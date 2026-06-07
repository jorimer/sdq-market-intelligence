"""Celery tasks for the banking module."""
from shared.tasks.celery_app import celery_app
from modules.banking_score.sib_sync import run_backfill


@celery_app.task(name="banking.sib_backfill", bind=True)
def sib_backfill_task(self, force: bool = False) -> dict:  # noqa: ARG001
    """Run the (incremental, idempotent) SIB backfill in the Celery worker."""
    return run_backfill(force=force)
