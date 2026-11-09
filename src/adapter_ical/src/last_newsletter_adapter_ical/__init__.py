"""Generic iCalendar feed implementation of core's `EventSource` port."""

__arbor__ = {"ring": "adapters"}

from last_newsletter_adapter_ical.client import IcalClient
from last_newsletter_adapter_ical.mapping import venue_from_location
from last_newsletter_adapter_ical.source import IcalConfig, IcalEventSource

__all__ = ["IcalClient", "IcalConfig", "IcalEventSource", "venue_from_location"]
