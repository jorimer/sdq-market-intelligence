# Development — SDQ Market Intelligence

> Tier 2 doc. Cárgalo cuando estés configurando ambiente local, corriendo migraciones, agregando un módulo nuevo, o necesites referenciar comandos no incluidos en Sensors.

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

## Adding a New Module

1. **Create folder**: `modules/{module_name}/` with `api/`, `models/`, `tests/`, `__init__.py`.
2. **Create routers** in `api/` (FastAPI `APIRouter`).
3. **Register routers** in `app/main.py` with prefix `/api/v1/{module-name}`.
4. **Create frontend module**: `frontend/src/modules/{module-name}/pages/` y `components/`.
5. **Add routes** to `frontend/src/App.tsx`.
6. **Subscribe to events** from other modules via `shared.events.event_bus` — nunca acceso directo a tablas de otro módulo.
