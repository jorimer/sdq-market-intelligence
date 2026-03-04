import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Predefined event type constants
RATING_COMPLETED = "rating.completed"
ANALYSIS_COMPLETED = "analysis.completed"
THRESHOLD_BREACH = "threshold.breach"
REPORT_GENERATED = "report.generated"
DATA_UPLOADED = "data.uploaded"


class EventBus:
    """In-process publish/subscribe event bus (singleton).

    Modules communicate through events, never by direct table access.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers: dict[str, list[Callable]] = defaultdict(list)
        return cls._instance

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Register a handler for an event type."""
        self._handlers[event_type].append(handler)
        logger.debug("Subscribed handler %s to event '%s'", handler.__name__, event_type)

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """Publish an event to all subscribed handlers."""
        logger.info("Event published: %s | payload keys: %s", event_type, list(payload.keys()))
        for handler in self._handlers.get(event_type, []):
            try:
                handler(payload)
            except Exception as e:
                logger.error(
                    "Error in handler %s for event '%s': %s",
                    handler.__name__, event_type, e,
                )

    def clear(self) -> None:
        """Remove all subscriptions (useful for testing)."""
        self._handlers.clear()


# Singleton instance
event_bus = EventBus()
