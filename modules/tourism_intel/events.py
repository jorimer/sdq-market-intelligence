"""Tourism Intel module events.

``tourism.updated`` is consumed by the products monitor (recálculo de readiness) via
shared.events.event_bus — never by direct table access.
"""
from typing import Any, Dict

from shared.events.event_bus import event_bus

TOURISM_UPDATED = "tourism.updated"


def publish_tourism_updated(payload: Dict[str, Any]) -> None:
    """Publish that the tourism traction score has been (re)computed."""
    event_bus.publish(TOURISM_UPDATED, payload)
