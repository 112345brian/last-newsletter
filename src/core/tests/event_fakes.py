"""Hand-written in-memory fakes for the event-ledger ports (no mocks)."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID

from last_newsletter_core.event_ports import CandidateQuery, ExtractionFailedError
from last_newsletter_core.events import (
    Event,
    EventCandidate,
    EventId,
    ItemState,
    Mention,
    local_date,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from ranked_digest.entities import EmailMessage


class SequentialIds:
    def __init__(self, start: int = 1) -> None:
        self._next = start

    def new_event_id(self) -> EventId:
        value = EventId(UUID(int=self._next))
        self._next += 1
        return value


class InMemoryEventRepository:
    def __init__(self, *, fail_on_write: int | None = None) -> None:
        self.events: dict[EventId, Event] = {}
        self.writes = 0
        self._fail_on_write = fail_on_write

    def _write(self) -> None:
        self.writes += 1
        if self._fail_on_write == self.writes:
            msg = "disk full"
            raise OSError(msg)

    def get(self, event_id: EventId) -> Event | None:
        return self.events.get(event_id)

    def find_candidates(self, query: CandidateQuery) -> list[Event]:
        return [
            e
            for e in self.events.values()
            if (query.uid is not None and e.uid == query.uid)
            or (query.url is not None and e.url == query.url)
            or query.date_from <= local_date(e.when) <= query.date_to
        ]

    def list_open(self) -> list[Event]:
        return [e for e in self.events.values() if e.state in {ItemState.OPEN, ItemState.SNOOZED}]

    def upsert(self, event: Event) -> None:
        self._write()
        self.events[event.id] = event

    def record_mention(self, event_id: EventId, mention: Mention) -> None:
        self._write()
        event = self.events[event_id]
        self.events[event_id] = replace(
            event,
            mentions=(*event.mentions, mention),
            last_seen=max(event.last_seen, mention.seen_at),
        )


class ScriptedReader:
    """Returns the candidates configured per message id; nothing otherwise."""

    def __init__(self, by_message: dict[str, list[EventCandidate]] | None = None) -> None:
        self._by_message = by_message or {}
        self.read_ids: list[str] = []

    def read(self, message: EmailMessage) -> list[EventCandidate]:
        self.read_ids.append(message.message_id)
        return list(self._by_message.get(message.message_id, []))


class ScriptedExtractor:
    """Returns the configured candidates; `fail_times` makes the first N calls raise."""

    def __init__(self, candidates: list[EventCandidate], *, fail_times: int = 0) -> None:
        self._candidates = candidates
        self._fail_times = fail_times
        self.calls: list[list[str]] = []

    def extract(
        self, messages: Sequence[EmailMessage], *, now: datetime, home_tz: str
    ) -> list[EventCandidate]:
        self.calls.append([m.message_id for m in messages])
        if self._fail_times > 0:
            self._fail_times -= 1
            msg = "model timeout"
            raise ExtractionFailedError(msg)
        return list(self._candidates)
