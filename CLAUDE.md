# SDQ Market Intelligence

## Architecture

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

### Key Principles
- **Modules are independent**: Each module in `modules/` has its own models, api, tests. Never import directly from another module.
- **Communication via events**: Modules communicate through `shared.events.event_bus`. No direct cross-module table access.
- **Shared is transversal**: Auth, narrative AI, database, config, notifications are shared services.
- **API per module**: Each module has its own prefix (`/api/v1/{module}/`).
- **Frontend per module**: Each module has its folder in `frontend/src/modules/`.

## Adding a New Module

1. Create folder: `modules/{module_name}/` with `api/`, `models/`, `tests/`, `__init__.py`
2. Create routers in `api/` (FastAPI APIRouter)
3. Register routers in `app/main.py` with prefix `/api/v1/{module-name}`
4. Create frontend module: `frontend/src/modules/{module-name}/pages/` and `components/`
5. Add routes to `frontend/src/App.tsx`
6. Subscribe to events from other modules via `shared.events.event_bus`

## Development Commands

```bash
# Backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev

# Docker
cd infrastructure && docker-compose up --build

# Database migrations
alembic -c infrastructure/alembic.ini upgrade head
alembic -c infrastructure/alembic.ini revision --autogenerate -m "description"

# Tests
pytest modules/ shared/ -v
pytest --cov=modules --cov=shared --cov-report=html
```

## Conventions

- **Python identifiers**: English (variable names, functions, classes)
- **UI strings**: Spanish (with i18n support for EN via `frontend/src/shared/i18n/`)
- **TypeScript**: Strict mode enabled
- **Tests**: Minimum 80% coverage on business logic before merge
- **API responses**: Error messages in Spanish
- **Database**: SQLAlchemy models, Alembic migrations, UUID primary keys

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy 2.0, Pydantic Settings, Alembic
- **Frontend**: React 18, Vite, TypeScript, Tailwind CSS, Recharts
- **AI**: Anthropic Claude (narrative generation, SCQA framework)
- **ML**: XGBoost (bank rating prediction)
- **Auth**: JWT (PyJWT) + bcrypt + RBAC (admin/analyst/viewer)
- **Database**: SQLite (dev), PostgreSQL 16 (prod)
- **Deploy**: Docker, Railway
