from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./data/sdq_market_intel.db"

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

    # Auth
    JWT_SECRET_KEY: str = "dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"

    # Secret used to encrypt stored API keys (data-source config). Falls back to
    # JWT_SECRET_KEY when unset so dev works out of the box; set explicitly in prod.
    SETTINGS_SECRET: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # SIB (Superintendencia de Bancos)
    SIB_API_KEY: str = ""
    SIB_API_BASE_URL: str = "https://apis.sb.gob.do/estadisticas/v2"

    # Redis (event bus + Celery broker/backend)
    REDIS_URL: str = ""
    # Route long background jobs (SIB backfill) through the Celery worker when a
    # worker is running. Off by default → jobs run in an in-process thread.
    USE_CELERY: bool = False

    # App
    DEFAULT_LANGUAGE: str = "es"
    REPORTS_DIR: str = "./data/reports"
    MODELS_DIR: str = "./data/models"
    CHARTS_DIR: str = "./data/charts"
    DEBUG: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Ignore unknown env vars (e.g. a legacy CLAUDE_MODEL after the rename to
        # ANTHROPIC_MODEL) instead of crashing the app on startup.
        extra = "ignore"


settings = Settings()
