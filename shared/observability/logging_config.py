"""Logging estructurado JSON, sin dependencias nuevas.

En producción (o con LOG_JSON=true) cada línea de log es un objeto JSON con
timestamp ISO, nivel, logger, mensaje, y —si los hay— la excepción y los campos
extra. Un colector (Railway, Datadog, etc.) lo parsea y permite alertar por nivel
o por campo. Fuera de producción se mantiene el texto plano legible de siempre.
"""
import datetime
import json
import logging
from typing import Any, Dict

from shared.config.settings import settings

# Atributos estándar de LogRecord — todo lo que NO esté aquí es un "extra" del
# llamador (logger.info(..., extra={...})) y se incluye en el JSON.
_RESERVED = frozenset(vars(logging.makeLogRecord({})).keys()) | {
    "message", "asctime", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Formatea cada LogRecord como un objeto JSON de una línea."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": datetime.datetime.fromtimestamp(
                record.created, tz=datetime.timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                try:
                    json.dumps(value)  # solo campos serializables
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = repr(value)
        return json.dumps(payload, ensure_ascii=False)


def use_json_logs() -> bool:
    return settings.LOG_JSON or settings.ENVIRONMENT.lower() == "production"


def configure_logging() -> None:
    """Configura el root logger (usado por app.main). JSON en prod, texto en dev."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    if use_json_logs():
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
    root.addHandler(handler)


def build_log_config() -> Dict[str, Any]:
    """dictConfig para uvicorn (--log-config se reemplaza por esto en start).

    Devuelve la config de uvicorn con el formatter JSON aplicado a default+access
    cuando corresponde, o el texto plano de uvicorn en dev.
    """
    if use_json_logs():
        fmt: Dict[str, Any] = {"()": "shared.observability.logging_config.JsonFormatter"}
        formatters = {"default": fmt, "access": fmt}
    else:
        formatters = {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
                "use_colors": False,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            },
        }
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": formatters,
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
    }
