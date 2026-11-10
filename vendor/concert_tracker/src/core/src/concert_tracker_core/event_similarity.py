"""Stdlib default for the `SimilarEventIndex` port: `difflib` over normalized title and venue."""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from concert_tracker_core.event_rules import normalize_text

if TYPE_CHECKING:
    from concert_tracker_core.events import Event, EventDraft, EventId


def _text(title: str, venue: str) -> str:
    return normalize_text(f"{title} {venue}")


class DifflibSimilarEventIndex:
    """In-memory index; forgets everything when the process ends (see `SimilarEventIndex`)."""

    def __init__(self) -> None:
        self._texts: dict[EventId, str] = {}

    def index(self, event: Event) -> None:
        self._texts[event.id] = _text(event.title, event.venue)

    def similar(self, candidate: EventDraft, *, limit: int) -> list[tuple[EventId, float]]:
        if limit <= 0:
            return []
        wanted = _text(candidate.title, candidate.venue)
        scored = [
            (event_id, SequenceMatcher(None, wanted, text).ratio())
            for event_id, text in self._texts.items()
        ]
        scored.sort(key=lambda pair: (-pair[1], str(pair[0])))
        return scored[:limit]
