"""Init de Sentry — captura de errores no manejados en producción.

No-op sin SENTRY_DSN (dev/tests) o si el SDK no está instalado. Con DSN, instrumenta
FastAPI (errores de request) y el logger (breadcrumbs + captura de ERROR).
"""
import logging

from shared.config.settings import settings

logger = logging.getLogger("sdq.observability")

_initialized = False


def init_sentry() -> bool:
    """Inicializa Sentry si hay DSN configurado. Devuelve True si quedó activo.

    Idempotente: llamarlo varias veces no re-inicializa.
    """
    global _initialized
    if _initialized:
        return True
    dsn = (settings.SENTRY_DSN or "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        logger.warning("SENTRY_DSN configurado pero sentry-sdk no está instalado.")
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        # Captura logging.error+ como eventos; INFO+ como breadcrumbs.
        integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
        # No enviar PII (headers de auth, cookies, body) por defecto.
        send_default_pii=False,
    )
    _initialized = True
    logger.info("Sentry inicializado (environment=%s)", settings.ENVIRONMENT)
    return True
