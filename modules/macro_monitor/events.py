"""Macro Monitor module events.

Other axes subscribe to ``macro.updated`` via shared.events.event_bus —
``sector_intel`` (dimensión Macro / Aceleración) and ``macro_political_risk``
(dimensión Macro del IRMP) — never by direct table access.
"""
from typing import Any, Dict

from shared.events.event_bus import event_bus

MACRO_UPDATED = "macro.updated"


def publish_macro_updated(payload: Dict[str, Any]) -> None:
    """Publish that a macro snapshot (momentum + signals) has been (re)computed."""
    event_bus.publish(MACRO_UPDATED, payload)
