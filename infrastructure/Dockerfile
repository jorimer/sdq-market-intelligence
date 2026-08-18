# ─── Stage 1: Frontend Build ───
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --production=false
COPY frontend/ ./
RUN npm run build

# ─── Stage 2: Backend + Serve Frontend ───
FROM python:3.11-slim AS production
WORKDIR /app

# System dependencies (libgomp for XGBoost, curl for healthcheck,
# tesseract + spanish + poppler for OCR of image-only fiduciary scans)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev libgomp1 curl \
    tesseract-ocr tesseract-ocr-spa poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies — lockfile con hashes (build reproducible). requirements.txt
# es la fuente de intención; requirements.lock la resolución fija (pip-compile en
# python:3.11-slim, mismo intérprete que esta imagen). --require-hashes falla si un
# paquete no está pinneado o su hash no coincide.
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# Copy backend code
COPY shared/ ./shared/
COPY modules/ ./modules/
COPY app/ ./app/
COPY scripts/ ./scripts/
# Corpus del motor de research (shared/knowledge/corpus): SOLO los docs de metodología
# de licencia clara del allowlist — NO todo docs/ (evita enviar handoffs/prompts con
# credenciales a la imagen). La doctrina versionada ya viaja en shared/. Si un doc falta,
# el loader degrada con gracia (pasaje ausente), no rompe. Mantener sincronizado con
# shared/knowledge/corpus/__init__.py::CORPUS_MANIFEST.
COPY docs/REPORT_STANDARD.md docs/DEEP_DIVE_FITCH_PARITY.md \
     docs/RUBRIC_AUDIT_AND_REMEDIATION.md docs/IRMP_SOURCE_UPGRADE_RESEARCH.md \
     docs/SPEC_PLATFORM_PRODUCTIZATION.md docs/SPEC_TIER_PRODUCTIZATION_BANKING.md \
     docs/RECETA_ONBOARDING_SECTOR.md docs/SERIES_CANONICAS_BCRD.md \
     docs/bcrd_estadisticas_catalog.md docs/sectorial-gate-e-data-spec.md \
     ./docs/
COPY infrastructure/alembic/ ./infrastructure/alembic/
COPY infrastructure/alembic.ini ./infrastructure/alembic.ini
COPY infrastructure/log_config.json ./infrastructure/log_config.json
COPY infrastructure/start.sh ./infrastructure/start.sh
RUN chmod +x ./infrastructure/start.sh

# Copy frontend build
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Create data directories
RUN mkdir -p data/reports data/models data/charts

# ── Sello del commit ───────────────────────────────────────────────────────────
# Va AL FINAL a propósito: cambia en cada commit y solo debe invalidar esta capa.
#
# Se hornea en la imagen además de leerse del entorno porque las dos vías fallan de formas
# distintas: la variable de ejecución depende de que la plataforma la inyecte, y la
# horneada viaja con la imagen aunque se despliegue a mano o en otro proveedor. Sin sello,
# `/health` responde `ok` con el proceso VIEJO cuando un despliegue falla — que fue el
# defecto que motivó esto.
ARG RAILWAY_GIT_COMMIT_SHA=""
ARG RAILWAY_GIT_BRANCH=""
ENV GIT_COMMIT=$RAILWAY_GIT_COMMIT_SHA \
    GIT_BRANCH=$RAILWAY_GIT_BRANCH

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000

# Role-aware entrypoint: web (migrations + uvicorn) or worker (Celery).
CMD ["sh", "infrastructure/start.sh"]
