"""Alertas accionables suscribibles — el producto de FLUJO de la plataforma.

Ver `docs/SPEC_ALERTA_ACCIONABLE.md`. Esta es la **fase A**: la watchlist (qué vigila cada
cliente) y su superficie HTTP. El motor de reglas, el gate y la entrega llegan en B/C.

**Por qué un módulo transversal y no uno de sector.** Recorre los 16 ejes del catálogo, así
que no puede vivir en ninguno (sería un import cross-módulo). Y no es una operación de
consola: es un producto que el cliente compra, no una tarea que el operador dispara.
"""
from shared.alerts.models import AlertDelivery, AlertEventRow, AlertSubscription

__all__ = ["AlertDelivery", "AlertEventRow", "AlertSubscription"]
