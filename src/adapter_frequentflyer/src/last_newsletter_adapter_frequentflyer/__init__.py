"""Frequent Flyer LA implementation of core's `EventSource` port."""

__arbor__ = {"ring": "adapters"}

from last_newsletter_adapter_frequentflyer.client import FrequentFlyerClient
from last_newsletter_adapter_frequentflyer.source import (
    FrequentFlyerConfig,
    FrequentFlyerEventSource,
)

__all__ = ["FrequentFlyerClient", "FrequentFlyerConfig", "FrequentFlyerEventSource"]
