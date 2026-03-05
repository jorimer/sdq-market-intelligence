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

# System dependencies (libgomp for XGBoost, curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY shared/ ./shared/
COPY modules/ ./modules/
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY infrastructure/alembic/ ./alembic/
COPY infrastructure/alembic.ini ./alembic.ini

# Copy frontend build
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Copy infrastructure configs
COPY infrastructure/railway.toml ./railway.toml

# Create data directories
RUN mkdir -p data/reports data/models data/charts

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
