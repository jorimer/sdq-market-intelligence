"""Recálculo de readiness disparado por eventos de datos.

Cuando cualquier fuente publica su ``*.updated`` (event_bus), recalculamos el readiness
del catálogo completo — barato (un solo sector con producto real hoy; el resto retorna
vacío al instante) y deja el monitor siempre fresco ante cualquier cambio de dato, sin
acoplar este paquete a ningún módulo (escucha eventos, no importa sectores).

Lo que este suscriptor NO hace (2026-08-20): disparar el pre-calentado de informes. Acá
vivía el disparo de ``prewarm-report-cache`` tras cada evento, y era el camino por el que el
pre-calentado seguía corriendo después de darlo por quitado: la cascada por evento no mira la
agenda, así que apagar el toggle de la consola no apagaba nada y el primer sync del día
volvía a generar informes que nadie pidió. El pre-calentado se eliminó entero; que no
reaparezca lo vigila ``shared/products/tests/test_regla_sin_precalentado.py``.
"""
import logging

from shared.database.session import SessionLocal
from shared.events.event_bus import event_bus
from shared.products.service import recompute_readiness

logger = logging.getLogger("sdq.products.events")

# Eventos de datos existentes en la plataforma. Al cablear un sector cuyo módulo
# publica su propio "*.updated" (como esg.updated en P4), añadirlo aquí para que su
# readiness se refresque solo. (banking aún no emite evento propio → manual/recompute.)
_TRACKED = ("macro.updated", "irmp.updated", "trade.updated", "sector.updated",
            "esg.updated", "energy.updated", "telecom.updated", "free_zones.updated",
            "tourism.updated", "construction.updated")


def _on_data_updated(payload: dict) -> None:
    db = SessionLocal()
    try:
        recompute_readiness(db)
    except Exception:  # noqa: BLE001 — un fallo de recálculo no debe romper al publicador
        logger.exception("Recálculo de readiness tras evento de datos falló")
        db.rollback()
    finally:
        db.close()


def subscribe_product_events() -> None:
    """Suscribe el recálculo a los eventos de datos. Idempotente a nivel de arranque."""
    for event_type in _TRACKED:
        event_bus.subscribe(event_type, _on_data_updated)
    logger.info("products suscrito a %s", ", ".join(_TRACKED))
