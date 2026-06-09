"""Celery application for background jobs (SIB backfill, future connector syncs).

Broker + result backend = Redis (``REDIS_URL``). Runs in a SEPARATE worker
process so a web (uvicorn) restart doesn't kill in-flight jobs; ``task_acks_late``
+ ``task_reject_on_worker_lost`` re-queue a task if the worker itself dies, so
it resumes automatically (paired with the idempotent, incremental backfill).
"""
from celery import Celery

from shared.config.settings import settings

celery_app = Celery(
    "sdq",
    broker=settings.REDIS_URL or None,
    backend=settings.REDIS_URL or None,
)

celery_app.conf.update(
    task_acks_late=True,                  # ack only after completion → re-queue on crash
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,         # one long job at a time
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    # The SIB backfill can run for hours (the carteras cube is ~100k rows/quarter).
    # Redis' default visibility_timeout is 1h, so a long task gets re-delivered
    # mid-run and executes again — a storm of redundant full backfills. Widen the
    # window past the longest expected run so an in-flight task is never re-queued
    # while still working. (Pairs with the dedup guard in run_backfill.)
    broker_transport_options={"visibility_timeout": 6 * 3600},
)

# Import task modules so the worker registers them.
celery_app.autodiscover_tasks(["modules.banking_score"])
