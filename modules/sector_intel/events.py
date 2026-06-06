"""Sector Intel events — publishes ``sector.updated`` and consumes the upstream
axes' events to feed the SGPS *Acceleration* factor.

Per the architecture, modules never import each other; we subscribe to the
upstream events purely by their string contract via shared.events.event_bus:
``macro.updated`` (macro_monitor), ``irmp.updated`` (macro_political_risk) and
``trade.updated`` (trade_intel).
"""
import logging
from typing import Any, Dict, Optional

from shared.events.event_bus import event_bus

logger = logging.getLogger("sdq.sector_intel.events")

SECTOR_UPDATED = "sector.updated"

# Upstream event names (string contract only — no cross-module imports).
_MACRO_UPDATED = "macro.updated"
_IRMP_UPDATED = "irmp.updated"
_TRADE_UPDATED = "trade.updated"


class AccelerationContext:
    """Holds the latest upstream signals used by the SGPS Acceleration factor."""

    def __init__(self) -> None:
        self.macro: Optional[Dict[str, Any]] = None
        self.irmp: Dict[str, Dict[str, Any]] = {}  # by country_code
        self.trade: Optional[Dict[str, Any]] = None

    def on_macro(self, payload: Dict[str, Any]) -> None:
        self.macro = payload

    def on_irmp(self, payload: Dict[str, Any]) -> None:
        code = payload.get("country_code")
        if code:
            self.irmp[code] = payload

    def on_trade(self, payload: Dict[str, Any]) -> None:
        self.trade = payload

    def reset(self) -> None:
        self.macro = None
        self.irmp = {}
        self.trade = None


# Singleton context kept fresh by the event bus.
acceleration_context = AccelerationContext()


def register_subscribers(bus=event_bus, context: AccelerationContext = acceleration_context) -> None:
    """Wire the acceleration context to upstream events (idempotent-ish)."""
    bus.subscribe(_MACRO_UPDATED, context.on_macro)
    bus.subscribe(_IRMP_UPDATED, context.on_irmp)
    bus.subscribe(_TRADE_UPDATED, context.on_trade)
    logger.info("sector_intel suscrito a macro/irmp/trade .updated")


def publish_sector_updated(payload: Dict[str, Any]) -> None:
    """Publish that a sector's IAI/SGPS has been (re)computed."""
    event_bus.publish(SECTOR_UPDATED, payload)
