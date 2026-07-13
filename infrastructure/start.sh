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
  # Bootstrap idempotente del super_admin real (solo crea si no existe ninguno y hay
  # SUPERADMIN_EMAIL/PASSWORD). No debe tumbar el deploy si algo falla.
  echo "Bootstrapping super_admin (si aplica)…"
  python scripts/bootstrap_superadmin.py || echo "bootstrap_superadmin: omitido/no crítico"
  # When Celery is enabled and there's no dedicated worker service, run a worker
  # in this container so queued jobs are consumed. acks_late re-queues on restart.
  if [ "$USE_CELERY" = "true" ]; then
    echo "Starting in-container Celery worker…"
    python -m celery -A shared.tasks.celery_app worker --loglevel=info --concurrency=1 &
  fi
  echo "Starting web (uvicorn)…"
  export SDQ_SCHEDULER=1  # in-app Operation Console scheduler (atomic-claim → safe with N workers)
  # Genera el log-config de uvicorn según el entorno: JSON en producción
  # (ENVIRONMENT=production o LOG_JSON=true), texto plano en dev. Un solo lugar de verdad
  # (shared/observability/logging_config.py). Fallback al JSON estático si algo falla.
  LOG_CFG=/tmp/uvicorn_log_config.json
  python -c "import json; from shared.observability.logging_config import build_log_config; json.dump(build_log_config(), open('$LOG_CFG','w'))" \
    || LOG_CFG=infrastructure/log_config.json
  exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 2 \
    --log-config "$LOG_CFG"
fi
