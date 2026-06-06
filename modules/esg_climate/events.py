"""ESG & Climate events — publishes ``esg.updated`` vía shared.events.event_bus."""
from typing import Any, Dict

from shared.events.event_bus import event_bus

ESG_UPDATED = "esg.updated"


def publish_esg_updated(payload: Dict[str, Any]) -> None:
    """Publish that ESG/climate exposure scores have been (re)computed."""
    event_bus.publish(ESG_UPDATED, payload)
