"""Venue-specific implementations of core's `EventSource` port, one small module per venue."""

__arbor__ = {"ring": "adapters"}

from last_newsletter_adapter_venues.client import JsonClient
from last_newsletter_adapter_venues.lodgeroom import LodgeRoomConfig, LodgeRoomEventSource
from last_newsletter_adapter_venues.scribble import ScribbleConfig, ScribbleEventSource

__all__ = [
    "JsonClient",
    "LodgeRoomConfig",
    "LodgeRoomEventSource",
    "ScribbleConfig",
    "ScribbleEventSource",
]
