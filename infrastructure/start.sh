#!/bin/sh
# Container entrypoint. One image, two roles (selected by SERVICE_ROLE):
#   - worker → Celery worker (background jobs: SIB backfill, etc.)
#   - web (default) → run DB migrations, then uvicorn. Behaviour identical to the
#     previous CMD, so the web service is unaffected by adding the worker.
set -e

if [ "$SERVICE_ROLE" = "worker" ]; then
  echo "Starting Celery worker (dedicated service)…"
  exec python -m celery -A shared.tasks.celery_app worker --loglevel=info --concurrency=1
else
  echo "Running migrations…"
  alembic -c infrastructure/alembic.ini upgrade head
  # When Celery is enabled and there's no dedicated worker service, run a worker
  # in this container so queued jobs are consumed. acks_late re-queues on restart.
  if [ "$USE_CELERY" = "true" ]; then
    echo "Starting in-container Celery worker…"
    python -m celery -A shared.tasks.celery_app worker --loglevel=info --concurrency=1 &
  fi
  echo "Starting web (uvicorn)…"
  export SDQ_SCHEDULER=1  # in-app Operation Console scheduler (atomic-claim → safe with N workers)
  exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 2 \
    --log-config infrastructure/log_config.json
fi
