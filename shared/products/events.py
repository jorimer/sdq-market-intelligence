"""Recálculo de readiness disparado por eventos de datos.

Cuando cualquier fuente publica su ``*.updated`` (event_bus), recalculamos el readiness
del catálogo completo — barato (un solo sector con producto real hoy; el resto retorna
vacío al instante) y deja el monitor siempre fresco ante cualquier cambio de dato, sin
acoplar este paquete a ningún módulo (escucha eventos, no importa sectores).
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


def _trigger_prewarm() -> None:
    """Re-calienta la caché de reportes tras un cambio de dato (op en background, deduped).

    Cierra la ventana en que la 1ª descarga vuelve a ser lenta desde que un sync refresca el
    dato hasta la corrida agendada (24h): un fingerprint nuevo invalida la caché de ese
    producto y la próxima descarga regeneraría (~15-90s). El disparo NO bloquea al publicador
    —``trigger`` lanza la op en su propio hilo— y el guard de "ya en curso" deduplica la
    tormenta de eventos de un deploy. El warm es idempotente: solo regenera lo que cambió."""
    try:
        from shared.operations.service import trigger
        res = trigger("prewarm-report-cache", origin="cascade", user_id=None)
        if not res.get("started"):
            logger.info("prewarm-report-cache no disparado tras evento: %s", res.get("reason"))
    except Exception:  # noqa: BLE001 — un fallo al encolar el warm no debe romper al publicador
        logger.exception("No se pudo disparar prewarm-report-cache tras evento de datos")


def _on_data_updated(payload: dict) -> None:
    db = SessionLocal()
    try:
        recompute_readiness(db)
    except Exception:  # noqa: BLE001 — un fallo de recálculo no debe romper al publicador
        logger.exception("Recálculo de readiness tras evento de datos falló")
        db.rollback()
    finally:
        db.close()
    # Con el dato ya refrescado, re-calentar la caché de reportes (background, idempotente).
    _trigger_prewarm()


def subscribe_product_events() -> None:
    """Suscribe el recálculo a los eventos de datos. Idempotente a nivel de arranque."""
    for event_type in _TRACKED:
        event_bus.subscribe(event_type, _on_data_updated)
    logger.info("products suscrito a %s", ", ".join(_TRACKED))
