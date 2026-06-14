"""Celery tasks for the banking module."""
from shared.tasks.celery_app import celery_app
from modules.banking_score.sib_sync import run_backfill


@celery_app.task(name="banking.sib_backfill", bind=True)
def sib_backfill_task(self, force: bool = False, only_tipos=None) -> dict:  # noqa: ARG001
    """Run the (incremental, idempotent) SIB backfill in the Celery worker.

    *only_tipos* restricts the run to the given entity types (targeted re-ingest).
    """
    return run_backfill(force=force, only_tipos=only_tipos)
