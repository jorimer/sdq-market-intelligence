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

### Los TRES gates de CI (los tres, no solo pytest)

```bash
pytest modules/ shared/ -q
ruff check modules/ shared/ app/                      # ruff==0.16.0
mypy shared/ modules/ app/ 2>&1 | mypy-baseline filter # mypy==1.17.1 + baseline
```

**`mypy-baseline` sale con código NO CERO también cuando RESOLVISTE deuda** ("Great work!").
Mirá el *exit code*, no el texto: si resolviste, corré `mypy shared/ modules/ app/ |
mypy-baseline sync` y comiteá el baseline. Y corré mypy sobre `shared/ modules/ app/` —
sobre un subdirectorio, el resto del baseline aparece como "resuelto" y el veredicto miente.

## Conventions

- **Python identifiers**: English (variable names, functions, classes)
- **UI strings**: Spanish (with i18n support for EN via `frontend/src/shared/i18n/`)
- **TypeScript**: Strict mode enabled
- **Tests**: Minimum 80% coverage on business logic before merge
- **API responses**: Error messages in Spanish
- **Database**: SQLAlchemy models, Alembic migrations, UUID primary keys

## Doctrina de datos y narrativa

Reglas que **no son estilo**: cada una salió de un defecto que llegó a producción y a un
documento que se vende. Violarlas vuelve a producir el mismo error.

**Declarar la brecha, nunca rellenarla.** Un dato ausente es `None`, jamás `0.0` ni un
promedio. Y si una métrica existe pero no mide lo que el eje afirma medir para esa entidad,
tampoco se publica: se declara el motivo en texto (ej. `ejecucion_no_publicable`). "No hay
dato" y "el dato existe y no mide esto" son cosas distintas, y la segunda es la interesante.

**Las relaciones se COMPUTAN, no se derivan.** Dirección (por encima/por debajo), superlativos,
deltas, rankings y posiciones se calculan en código y el modelo los COPIA. El modelo acierta
las cifras y falla las relaciones.

**El SUJETO viaja con el número.** Toda clave de cuota/participación/concentración debe nombrar
su población: `concentracion_top4_ramos_pct`, no `concentracion_top4_pct`. El modelo reatribuye
al sujeto más cercano — así se publicó «cuatro compañías concentran el 87,1%» cuando eran
cuatro ramos. Si no tenés la cifra que el modelo va a necesitar, pasásela igual con su nombre
real: dejar el hueco es lo que lo llena mal. Lo vigila
`shared/narrative/tests/test_regla_sujeto_en_contexto.py`.

**Solo se ordena lo comparable.** Un score armado sobre 3 de 5 dimensiones no rankea contra uno
de 5. Usá `shared.narrative.derived.universo_comparable`; los parciales no se ocultan (eso los
hace desaparecer sin aviso), van aparte y marcados. Aplica al contexto de IA **y** a la tabla
renderizada: son superficies distintas y arreglar una sola deja el documento contradiciéndose.

**Dónde vive el contexto del modelo.** Por defecto `modules/<mod>/ai_context.py`. Si tu módulo
lo arma en otro lado, declaralo en `AI_CONTEXT_FILES` (ver `banking_score/products.py`) o
quedará fuera de la regla del sujeto y de la huella de la caché de narrativas.

**El estado de validación de un eje se COMPUTA y se declara; nunca se transcribe.** Es la
regla que salió del plan de cierre (2026-08-19), y tiene tres piezas que hay que respetar:

- **Qué puede afirmar cada eje** lo declara su producto en `ESTADO_BACKTEST` (clase, no el
  `ValidationState` que devuelve el método: varios ejes tienen ramas de retorno distintas y el
  hueco entra por la que alguien olvidó). Declara hechos de DISEÑO —si hay motor, contra qué
  desenlace, qué lo impide— y **nunca el veredicto de la última corrida**, que envejece. Lo
  exige `shared/products/tests/test_estado_de_validacion.py`, que además **cruza contra
  `shared.validation.frescura.MOTORES`**: un producto no puede reclamar un motor que nadie
  registró. Triaje completo en `docs/TRIAJE_VALIDACION_EJES.md`.
- **El veredicto vigente** (Gini/IC/N, concluyente o no) vive en el reporte del motor y se lee
  de ahí: `GET /api/v1/products/credenciales` arma la tabla comercial computándola.
  **Ninguna cifra de validación se escribe a mano** — ni en un doc, ni en un deck, ni en una
  memoria. Un número copiado es un número que se desincroniza.
- **La frescura veta.** `stale=false` publica; `stale=true` no; y **`stale=null` tampoco** —
  «no sé de cuándo es» y «está al día» son cosas distintas, y confundirlas fue lo que puso un
  Gini de 0,44 en producción durante 19 días contra un deck que decía 0,16. Lo vetado se
  LISTA, no desaparece: un veto silencioso se lee como que el eje no tiene validación.
  Estado en vivo: `GET /api/v1/operations/validacion`.

Un eje NUEVO entra al catálogo declarando su estado o el test estructural lo rechaza. Y si
querés saber cómo está un eje hoy, **preguntale a la plataforma** — no busques una tabla en un
documento, porque cualquier tabla escrita ya está vieja. Qué se puede decir en material de
venta: `docs/CLAIMS_COMERCIALES.md`.

**Qué invalida la caché de narrativas** (`ProductReportCache`, en Postgres, **sin TTL**): el
dato, la receta (prompts/doctrina/modelo/guard) y el contexto declarado. Si tu arreglo no toca
ninguno, los informes ya generados seguirán sirviendo el texto viejo indefinidamente.
**Al verificar en prod, el tiempo de respuesta es el dato: menos de ~2 s es un HIT y no
verificaste nada.** Una generación real toma 15-90 s.

**La prosa que el modelo debe respetar vive en CONSTANTES**, no incrustada en un dict: un
literal se parte por ancho de línea y la frase deja de existir en el fuente aunque el valor sea
correcto, así que un test que la busque ahí falla sin motivo (o pasa sin protegerte).

**Cuando un defecto se repite entre motores, la cura es un TEST ESTRUCTURAL** que lee el código
con `ast` y exige la regla o una excepción declarada. La lección escrita ya falló siete veces
en este repo. Al escribir el glob del test, preguntate **qué queda afuera**. Y antes de escribir
un guard, buscá si otro módulo ya lo resolvió — suele estar, y suele estar mejor.

**Un test del motor NO es un test de la ruta.** Los guardrails viven en el motor y la ruta se
queda sin probar: van cinco defectos así. El último no fue de contexto sino de REGISTRO —un
helper se coló entre el decorador y su función, y `GET .../informe-abierto` devolvió una fecha
con HTTP 200 mientras los tests de `render()` seguían verdes—. Lo vigila
`shared/tests/test_toda_ruta_recibe_su_path.py`, que exige que toda función reciba los
parámetros que su path declara. Cuando el entregable sale por HTTP, **pedilo por HTTP**.

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy 2.0, Pydantic Settings, Alembic
- **Frontend**: React 18, Vite, TypeScript, Tailwind CSS, Recharts
- **AI**: Anthropic Claude (narrative generation, SCQA framework)
- **ML**: XGBoost (bank rating prediction)
- **Auth**: JWT (PyJWT) + bcrypt + RBAC (admin/analyst/viewer)
- **Database**: SQLite (dev), PostgreSQL 16 (prod)
- **Deploy**: Docker, Railway
