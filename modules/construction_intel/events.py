"""Construction Intel module events.

``construction.updated`` is consumed by the products monitor (recálculo de readiness) via
shared.events.event_bus — never by direct table access.
"""
from typing import Any, Dict

from shared.events.event_bus import event_bus

CONSTRUCTION_UPDATED = "construction.updated"


def publish_construction_updated(payload: Dict[str, Any]) -> None:
    """Publish that the construction conjuncture score (ICC) has been (re)computed."""
    event_bus.publish(CONSTRUCTION_UPDATED, payload)
