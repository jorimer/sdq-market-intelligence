"""Macro-Political Risk module events.

Other modules (SGPS, Banking Score, Deal Scoring) subscribe to ``irmp.updated``
via shared.events.event_bus — never by direct table access.
"""
from typing import Any, Dict

from shared.events.event_bus import event_bus

IRMP_UPDATED = "irmp.updated"


def publish_irmp_updated(payload: Dict[str, Any]) -> None:
    """Publish that a country's IRMP score has been (re)computed."""
    event_bus.publish(IRMP_UPDATED, payload)
