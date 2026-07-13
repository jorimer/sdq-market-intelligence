"""Observabilidad transversal: logs JSON estructurados, init de Sentry y health
checks profundos. Cierra la brecha 4 de la DD (producción ciega).

Sin SENTRY_DSN, el init de Sentry es un no-op — dev y tests no requieren nada.
Los logs son texto plano legible salvo en producción (o con LOG_JSON=true), donde
salen como JSON de una línea parseable por el colector de Railway.
"""
from shared.observability.logging_config import build_log_config, configure_logging
from shared.observability.sentry import init_sentry

__all__ = ["build_log_config", "configure_logging", "init_sentry"]
