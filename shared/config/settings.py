from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./data/sdq_market_intel.db"

    # Claude AI
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-sonnet-4-5-20250929"

    # Auth
    JWT_SECRET_KEY: str = "dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # SIB (Superintendencia de Bancos)
    SIB_API_KEY: str = ""
    SIB_API_BASE_URL: str = "https://apis.sb.gob.do/estadisticas/v2"

    # Redis (optional, for event bus)
    REDIS_URL: str = ""

    # App
    DEFAULT_LANGUAGE: str = "es"
    REPORTS_DIR: str = "./data/reports"
    MODELS_DIR: str = "./data/models"
    CHARTS_DIR: str = "./data/charts"
    DEBUG: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
