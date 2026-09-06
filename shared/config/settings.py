from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./data/sdq_market_intel.db"

    # Pool de conexiones (solo PostgreSQL). Se DECLARA en vez de heredar en silencio el
    # default de SQLAlchemy, porque el número que importa no es el de un proceso: cada
    # worker web y el de Celery abren SU pool, y cada conexión es un backend de Postgres
    # con su propia memoria. Con 2 workers eso permite hasta 30 conexiones del web más las
    # de Celery, y nadie había elegido ese techo — era el default de una biblioteca.
    #
    # **POR QUÉ EL VALOR NO BAJA TODAVÍA.** Declarar el número y CAMBIARLO son dos cosas
    # distintas, y la segunda sin medición es sustituir el default de una biblioteca por una
    # corazonada. El riesgo no es teórico: una generación de narrativa tarda 15-90 s, y si
    # esa sesión se sostiene mientras el modelo responde, bajar el techo a 10 hace que la
    # 11ª petición espere hasta `pool_timeout` (30 s) antes de fallar. Se paga en latencia
    # de cliente para ahorrar memoria que todavía nadie contó.
    #
    # Así que estos valores REPRODUCEN el comportamiento de hoy (5 + 10) y lo que este
    # cambio agrega es el instrumento: `GET /api/v1/operations/base-de-datos` publica el
    # uso real del pool. Con esa cifra el techo se baja con dato, en un cambio propio y
    # reversible de una variable de entorno.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    # Railway corta las conexiones ociosas por su lado: sin reciclado, la app se queda con
    # conexiones muertas que fallan en la primera consulta. `pool_pre_ping` las detecta y
    # `pool_recycle` las renueva antes de que pase.
    DB_POOL_RECYCLE_SECONDS: int = 1800

    # Claude AI. The model env var is ANTHROPIC_MODEL (the code previously read
    # CLAUDE_MODEL, so a configured ANTHROPIC_MODEL was silently ignored). Default
    # is a current model; override via the ANTHROPIC_MODEL env var.
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"
    # Model used by the numeric anti-hallucination guardrail (cerebro route): judges
    # whether every figure in an insight traces to the context — including period↔value
    # correspondence and the arithmetic of relative/derived claims, which need a capable
    # model (Haiku missed wrong-period values and miscomputed deltas in the pilot sensor).
    # Override via the ANTHROPIC_GUARD_MODEL env var.
    ANTHROPIC_GUARD_MODEL: str = "claude-sonnet-4-6"
    # Máximo de llamadas CONCURRENTES al API de Anthropic (semáforo global del motor de
    # narrativa). Es el TECHO REAL de throughput del warmer y de las descargas frescas:
    # las secciones de un reporte se generan en paralelo (asyncio.gather), acotadas por esta
    # cota para no rozar el rate limit (429). Subirlo acelera; el cliente reintenta 429 con
    # backoff, pero si se satura el rate el reintento agota → fallback estático (peor calidad).
    # Ajustar según el tier del API key. Override via NARRATIVE_MAX_CONCURRENCY.
    NARRATIVE_MAX_CONCURRENCY: int = 10
    # Presupuesto DIARIO de gasto LLM en USD (0 = sin techo). Al superarlo se activa
    # el corte SUAVE: la narrativa degrada a caché/fallback estático, el router
    # semántico cae al contexto curado y el juez LLM del guardrail se omite (la capa
    # determinista sigue). Nada lanza error; se loguea un warning por hora. El
    # contador vive en Redis (compartido entre workers) — ver shared/llm/budget.py.
    #
    # El default NO es 0. Un entorno que nunca definió la variable quedaba sin techo, y
    # "sin techo" no es una decisión que nadie tomó: es la que se toma sola. El 2026-08-20
    # una tarea de pre-calentado generó informes que nadie pidió y gastó USD 127 en un día
    # sin que nada pudiera cortarla, porque para el contador el techo no existía. 25 es un
    # valor de ARRANQUE deliberadamente holgado frente al uso legítimo y estrecho frente a
    # una fuga; el número real se calibra mirando el gasto propio en
    # ``GET /api/v1/operations/llm-spend`` y se fija por variable de entorno.
    #
    # Cuidado al bajarlo: sobre el techo, una entrega premium NO sirve texto degradado —
    # devuelve 503 (ver ``shared/products/router.py``). Un techo por debajo del uso real
    # convierte gasto en clientes sin su informe. Se apaga con 0, a sabiendas.
    LLM_DAILY_BUDGET_USD: float = 25.0

    # Enrutador SEMÁNTICO de dominios del motor de research (el Cerebro decide qué motores
    # convoca la pregunta). OFF por defecto: su despliegue con cosecha concurrente en
    # worker-threads mataba al worker uvicorn (SIGKILL, sin traceback) en TODA consulta sin
    # caché. Con OFF, el orquestador usa el contexto CURADO + cosecha secuencial (camino
    # probado). Re-activar (=true) sólo tras diagnosticar el crash con métricas de memoria.
    RESEARCH_SEMANTIC_ROUTER: bool = False

    # Verificación de relevancia tema-pasaje del gate de honestidad (A4.2 de
    # docs/SPEC_GATE_HONESTIDAD_Y_FUENTES_DGII.md): antes de anclar RUBRIC con doctrina/
    # metodología, una llamada LLM sí/no valida que el pasaje sea método APLICABLE a la
    # sub-pregunta. ON por defecto (es el fix estructural); es una válvula operativa para
    # apagarlo sin deploy si hiciera falta. Fail-safe: sin Cerebro/presupuesto/error → GAP.
    RESEARCH_RELEVANCE_CHECK: bool = True

    # Verificación de pertinencia de ENTIDAD del research custom: cuando el matcher léxico
    # resuelve una entidad con match DÉBIL (token ambiguo, o sin que la pregunta active su
    # eje), una llamada LLM sí/no confirma que la pregunta trate de esa entidad antes de
    # anclar el informe a su ficha (el informe McDonald's quedó anclado a Citibank por la
    # palabra "sucursal"). Fail-safe INVERSO a la relevancia: sin Cerebro/presupuesto/error
    # → la entidad se CONSERVA (el piso determinista no depende del LLM).
    RESEARCH_ENTITY_CHECK: bool = True

    # Auth
    JWT_SECRET_KEY: str = "dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    # Orígenes permitidos para CORS (coma-separados). La SPA de prod se sirve del MISMO
    # dominio que el API (same-origin, no necesita CORS); esta lista cubre el dev server
    # de Vite y cualquier origen extra que el dueño agregue (p. ej. un dominio propio).
    # Antes era "*" con credenciales — brecha 2 del DD.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Secret used to encrypt stored API keys (data-source config). Falls back to
    # JWT_SECRET_KEY when unset so dev works out of the box; set explicitly in prod.
    SETTINGS_SECRET: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # SIB (Superintendencia de Bancos)
    SIB_API_KEY: str = ""
    #: Entidades con las que SDQ Consulting mantiene una relación profesional (nombres o ids,
    #: separados por coma). Para ellas la sección de cierre de una valuación DECLARA la
    #: relación en vez de afirmar independencia. Vacío = ninguna. Decisión del dueño 2026-09-06.
    VALUACION_ENTIDADES_CON_RELACION: str = ""
    SIB_API_BASE_URL: str = "https://apis.sb.gob.do/estadisticas/v2"

    # Redis (event bus + Celery broker/backend)
    REDIS_URL: str = ""
    # Route long background jobs (SIB backfill) through the Celery worker when a
    # worker is running. Off by default → jobs run in an in-process thread.
    USE_CELERY: bool = False

    # Correo saliente (entrega de alertas fuera de la app). SMTP y no un SDK de proveedor:
    # SendGrid, Resend, SES y Postmark exponen todos SMTP, así que el emisor no queda casado
    # con ninguno y no suma una dependencia al lock —que ya tiene su propio problema en macOS.
    #
    # **Sin host configurado, el canal `email` NO se ofrece.** No es un detalle de despliegue:
    # aceptar una vigilancia por un canal que no entrega deja al cliente esperando avisos que
    # nunca salen, y un canal mudo no falla — desaparece. Ver `shared/notifications/email.py`.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    # Remitente. Vacío ⇒ se usa SMTP_USER. Acepta "Nombre <casilla@dominio>".
    SMTP_FROM: str = ""
    SMTP_STARTTLS: bool = True
    # Base pública de la app, para los enlaces del correo ("administrá tus vigilancias").
    # Un correo sin salida es un correo que se marca como spam.
    APP_PUBLIC_URL: str = "https://sdq-market-intelligence-production.up.railway.app"

    # App
    DEFAULT_LANGUAGE: str = "es"
    REPORTS_DIR: str = "./data/reports"
    MODELS_DIR: str = "./data/models"
    CHARTS_DIR: str = "./data/charts"
    DEBUG: bool = False

    # Observability
    # Nombre del entorno (development/staging/production) — etiqueta los eventos de
    # Sentry y decide el formato de logs. En prod, ENVIRONMENT=production activa logs JSON.
    ENVIRONMENT: str = "development"
    # Sentry: sin DSN, la instrumentación es un no-op (no rompe dev/tests). El dueño
    # crea el proyecto y setea SENTRY_DSN en Railway.
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0
    # Forzar logs JSON estructurados aunque ENVIRONMENT no sea production (debug).
    LOG_JSON: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Ignore unknown env vars (e.g. a legacy CLAUDE_MODEL after the rename to
        # ANTHROPIC_MODEL) instead of crashing the app on startup.
        extra = "ignore"


settings = Settings()
