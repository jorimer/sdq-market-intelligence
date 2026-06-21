# SDQ Market Intelligence

## Project Overview

Modular financial intelligence platform for the Dominican Republic and Caribbean banking sector.

```
sdq-market-intelligence/
├── shared/          # Cross-cutting services (auth, database, narrative AI, events, config)
├── modules/         # Feature modules (each self-contained with api/, models/, tests/)
│   └── banking_score/   # Module 1: Banking Score (19 indicators, 10-tier rating scale)
├── app/             # FastAPI entry point (main.py)
├── frontend/        # React SPA (Vite + TypeScript + Tailwind)
└── infrastructure/  # Docker, Alembic, Railway
```

## Key Principles (always apply)

- **Modules are independent**: Each module in `modules/` has its own models, api, tests. **Never** import directly from another module.
- **Communication via events**: Modules communicate through `shared.events.event_bus`. **No direct cross-module table access.**
- **Shared is transversal**: Auth, narrative AI, database, config, notifications are shared services.
- **API per module**: Each module has its own prefix (`/api/v1/{module}/`).
- **Frontend per module**: Each module has its folder in `frontend/src/modules/`.

## Conventions

- **Python identifiers**: English (variable names, functions, classes).
- **UI strings**: Spanish (with i18n support for EN via `frontend/src/shared/i18n/`).
- **TypeScript**: Strict mode enabled.
- **Tests**: Minimum 80% coverage on business logic before merge.
- **API responses**: Error messages in Spanish.
- **Database**: SQLAlchemy models, Alembic migrations, UUID primary keys.

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy 2.0, Pydantic Settings, Alembic.
- **Frontend**: React 18, Vite, TypeScript, Tailwind CSS, Recharts.
- **AI**: Anthropic Claude (narrative generation, SCQA framework).
- **ML**: XGBoost (bank rating prediction).
- **Auth**: JWT (PyJWT) + bcrypt + RBAC (admin/analyst/viewer).
- **Database**: SQLite (dev), PostgreSQL 16 (prod).
- **Deploy**: Docker, Railway.

## Tier 2 Docs (load on demand)

- [`docs/agent/development.md`](docs/agent/development.md) — comandos de setup, migraciones Alembic, y guía para agregar un módulo nuevo. Carga cuando vayas a crear un módulo, configurar ambiente, o correr migraciones.

## Sensors (verificación determinista)

Antes de marcar una tarea como completa, corre los comandos relevantes al cambio y reporta el resultado. Si un sensor falla, no cierres la tarea — itera hasta resolverlo o documenta explícitamente por qué se acepta el fallo.

**Backend (raíz, Python + FastAPI)**
- Lint (ruff, line-length 100): `ruff check .`
- Auto-fix lint donde aplique: `ruff check . --fix`
- Tests por módulo (donde existan): `pytest modules/<module>/tests/`
- Tests globales si el cambio toca varios módulos: `pytest`

**Frontend (`frontend/`)**
- Type-check + build (incluye `tsc`): `cd frontend && npm run build`
- Preview de la build: `cd frontend && npm run preview`

**Cuándo correr qué**
- Cambio solo backend Python → `ruff check .` + tests del módulo afectado.
- Cambio solo frontend → build.
- Cambio cross-stack → ambos.
- Cambio en el modelo XGBoost o en lógica de bank scoring → tests específicos del módulo `banking_score/` y validación de que la predicción se mantiene en el rango esperado contra el dataset de referencia.
- Cambio que toca JWT o RBAC → tests de autenticación y verificación manual de los tres roles (admin/analyst/viewer).
