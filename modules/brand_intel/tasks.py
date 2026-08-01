"""Celery tasks for the brand intel module."""
from shared.tasks.celery_app import celery_app
from modules.brand_intel.ingest.jobs import run_extraction


@celery_app.task(name="brand_intel.read_deck", bind=True)
def read_deck_task(self, extraction_id: str) -> dict:  # noqa: ARG001
    """Read one presentation in the worker, out of the web request's way.

    Safe to re-deliver: ``run_extraction`` resumes from the slides already committed, so
    ``task_acks_late`` re-queueing a job whose worker died does not pay for the reading
    twice — which is the property that makes acks_late affordable here at all.
    """
    return run_extraction(extraction_id)
