"""Trade Intel module events.

``trade.updated`` is consumed by ``sector_intel`` (resiliencia/MRS) and by the
IRMP (dimensión externa) via shared.events.event_bus — never by direct table access.
"""
from typing import Any, Dict

from shared.events.event_bus import event_bus

TRADE_UPDATED = "trade.updated"


def publish_trade_updated(payload: Dict[str, Any]) -> None:
    """Publish that the trade-resilience score has been (re)computed."""
    event_bus.publish(TRADE_UPDATED, payload)
