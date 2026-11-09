"""Squarespace events-page implementation of core's `EventSource` port."""

__arbor__ = {"ring": "adapters"}

from last_newsletter_adapter_squarespace.client import SquarespaceClient
from last_newsletter_adapter_squarespace.mapping import is_date_like
from last_newsletter_adapter_squarespace.source import SquarespaceConfig, SquarespaceEventSource

__all__ = ["SquarespaceClient", "SquarespaceConfig", "SquarespaceEventSource", "is_date_like"]
