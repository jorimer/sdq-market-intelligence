"""Social Development events — publishes ``social.updated`` (consumido por
reports / publicaciones del think tank) vía shared.events.event_bus.
"""
from typing import Any, Dict

from shared.events.event_bus import event_bus

SOCIAL_UPDATED = "social.updated"


def publish_social_updated(payload: Dict[str, Any]) -> None:
    """Publish that development scores have been (re)computed."""
    event_bus.publish(SOCIAL_UPDATED, payload)
