"""Telecom Intel module events.

``telecom.updated`` is consumed by the products monitor (recálculo de readiness) via
shared.events.event_bus — never por acceso directo a tablas.
"""
from typing import Any, Dict

from shared.events.event_bus import event_bus

TELECOM_UPDATED = "telecom.updated"


def publish_telecom_updated(payload: Dict[str, Any]) -> None:
    """Publish that the telecom-development score has been (re)computed."""
    event_bus.publish(TELECOM_UPDATED, payload)
