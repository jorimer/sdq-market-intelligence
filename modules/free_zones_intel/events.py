"""Free Zones Intel module events.

``free_zones.updated`` is consumed by the products monitor (recálculo de readiness) via
shared.events.event_bus — never by direct table access.
"""
from typing import Any, Dict

from shared.events.event_bus import event_bus

FREE_ZONES_UPDATED = "free_zones.updated"


def publish_free_zones_updated(payload: Dict[str, Any]) -> None:
    """Publish that the free-zone attractiveness score has been (re)computed."""
    event_bus.publish(FREE_ZONES_UPDATED, payload)
