"""Banking Score events.

Publishes ``rating.completed`` and **consumes** ``irmp.updated`` to overlay the
sovereign/macro-political environment onto an entity's *outlook* — never onto its
intrinsic score (SPEC §6).  Consumed purely by the string contract via the event
bus (no cross-module imports).
"""
import logging
from typing import Any, Dict

from shared.events.event_bus import event_bus

logger = logging.getLogger("sdq.banking_score.events")

RATING_COMPLETED = "rating.completed"
_IRMP_UPDATED = "irmp.updated"


def publish_rating_completed(payload: Dict[str, Any]) -> None:
    event_bus.publish(RATING_COMPLETED, payload)


class IRMPOutlookContext:
    """Holds the latest IRMP read per country to bias entity outlook."""

    def __init__(self) -> None:
        self.by_country: Dict[str, Dict[str, Any]] = {}

    def on_irmp(self, payload: Dict[str, Any]) -> None:
        code = payload.get("country_code")
        if code:
            self.by_country[code] = payload

    def band(self, country_code: str) -> str | None:
        snap = self.by_country.get(country_code)
        return snap.get("risk_band") if snap else None

    def reset(self) -> None:
        self.by_country = {}


irmp_outlook_context = IRMPOutlookContext()


def register_subscribers(bus=event_bus, context: IRMPOutlookContext = irmp_outlook_context) -> None:
    """Wire the IRMP outlook context to ``irmp.updated``."""
    bus.subscribe(_IRMP_UPDATED, context.on_irmp)
    logger.info("banking_score suscrito a irmp.updated (overlay de outlook)")


# Outlook overlay -------------------------------------------------------------
# A high-risk macro-political environment biases the outlook negative; a low-risk
# one allows a positive bias.  The intrinsic score is never touched.

_NEGATIVE_BANDS = {"Elevado", "Alto"}
_POSITIVE_BANDS = {"Bajo"}


def overlay_outlook(base_outlook: str, country_code: str = "DO",
                    context: IRMPOutlookContext = irmp_outlook_context) -> Dict[str, Any]:
    """Return the (possibly adjusted) outlook plus the IRMP reason.

    Args:
        base_outlook: "positiva" | "negativa" | "estable" (from score delta).
        country_code: sovereign whose IRMP applies (default "DO").

    Returns ``{"outlook", "irmp_band", "adjusted"}``.
    """
    band = context.band(country_code)
    outlook = base_outlook
    if band in _NEGATIVE_BANDS and base_outlook == "estable":
        outlook = "negativa"
    elif band in _POSITIVE_BANDS and base_outlook == "estable":
        outlook = "positiva"
    return {"outlook": outlook, "irmp_band": band, "adjusted": outlook != base_outlook}
