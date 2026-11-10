"""Where new event ids come from. Randomness is an effect, so it lives outside core."""

from __future__ import annotations

__arbor__ = {"ring": "app"}

from typing import Protocol
from uuid import uuid4

from concert_tracker_core.events import EventId


class IdGenerator(Protocol):
    def new_event_id(self) -> EventId: ...


class Uuid4Ids:
    """`IdGenerator`: random UUIDs (randomness is an effect, so it lives outside core)."""

    def new_event_id(self) -> EventId:
        return EventId(uuid4())
