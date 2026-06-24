"""Energy Intel module events.

``energy.updated`` is consumed by the products monitor (recálculo de readiness) via
shared.events.event_bus — never by direct table access.
"""
from typing import Any, Dict

from shared.events.event_bus import event_bus

ENERGY_UPDATED = "energy.updated"


def publish_energy_updated(payload: Dict[str, Any]) -> None:
    """Publish that the energy-resilience score has been (re)computed."""
    event_bus.publish(ENERGY_UPDATED, payload)
