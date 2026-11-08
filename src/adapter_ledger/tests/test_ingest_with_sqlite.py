"""End to end: core's `IngestEvents` running against the SQLite repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from last_newsletter_adapter_ledger import SqliteEventRepository
from last_newsletter_core.events import (
    EntityRef,
    EntityRole,
    EventCandidate,
    EventId,
    ItemState,
    MatchRule,
    PartialWhen,
)
from last_newsletter_core.use_cases import IngestEvents, IngestPorts, IngestResult
from ranked_digest.entities import EmailMessage

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


class _Ids:
    def __init__(self) -> None:
        self._n = 0

    def new_event_id(self) -> EventId:
        self._n += 1
        return EventId(UUID(int=self._n))


class _NoReader:
    def read(self, message: EmailMessage) -> list[EventCandidate]:
        return []


class _Scripted:
    def __init__(self, candidates: list[EventCandidate]) -> None:
        self.candidates = candidates

    def extract(
        self, messages: Sequence[EmailMessage], *, now: datetime, home_tz: str
    ) -> list[EventCandidate]:
        ids = {m.message_id for m in messages}
        return [c for c in self.candidates if c.message_id in ids]


def _message(message_id: str, body: str = "Band at Venue, Dec 12.") -> EmailMessage:
    return EmailMessage(
        message_id=message_id,
        sender="promo@example.com",
        subject="Shows",
        received_at=datetime(2026, 11, 5, tzinfo=UTC),
        body_text=body,
        source_label="promoter",
    )


def _candidate(message_id: str, **overrides: object) -> EventCandidate:
    base = EventCandidate(
        message_id=message_id,
        title="Band at Venue",
        when=PartialWhen(year=2026, month=12, day=12, raw_text="Dec 12"),
        evidence="Band at Venue, Dec 12",
        entities=(EntityRef(name="The Venue", role=EntityRole.VENUE),),
    )
    return replace(base, **overrides)


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[SqliteEventRepository]:
    with SqliteEventRepository(tmp_path / "ledger.db") as repository:
        yield repository


def _ingest(
    repo: SqliteEventRepository, candidates: list[EventCandidate], messages: list[EmailMessage]
) -> IngestResult:
    ports = IngestPorts(
        repository=repo, reader=_NoReader(), extractor=_Scripted(candidates), ids=_Ids()
    )
    return IngestEvents(ports, home_tz="America/New_York").ingest(messages, now=_NOW)


def test_reingesting_the_same_message_adds_nothing(repo: SqliteEventRepository) -> None:
    candidates = [_candidate("m1")]
    assert _ingest(repo, candidates, [_message("m1")]).created == 1
    before = repo.list_open()
    again = _ingest(repo, candidates, [_message("m1")])
    assert (again.created, again.mentioned) == (0, 0)
    assert repo.list_open() == before
    assert len(before) == 1
    assert len(before[0].mentions) == 1


def test_a_later_mention_cites_the_first_events_uuid(repo: SqliteEventRepository) -> None:
    url = "https://example.com/e"
    assert _ingest(repo, [_candidate("m1", url=url)], [_message("m1")]).created == 1
    (first,) = repo.list_open()
    second = _ingest(
        repo,
        [_candidate("m2", url=url, evidence="Band at Venue, Dec 12 tickets")],
        [_message("m2", "Band at Venue, Dec 12 tickets")],
    )
    assert (second.created, second.mentioned) == (0, 1)
    (only,) = repo.list_open()
    assert only.id == first.id
    assert [m.message_id for m in only.mentions] == ["m1", "m2"]
    assert only.mentions[1].match_rule is MatchRule.URL
    assert {m.cited_event_id for m in only.mentions} == {first.id}


def test_owner_decision_survives_a_new_mention(repo: SqliteEventRepository) -> None:
    url = "https://example.com/e"
    assert _ingest(repo, [_candidate("m1", url=url)], [_message("m1")]).created == 1
    (first,) = repo.list_open()
    repo.set_owner_state(first.id, ItemState.DONE)
    second = _ingest(
        repo,
        [_candidate("m2", url=url, evidence="Dec 12 again")],
        [_message("m2", "Band at Venue Dec 12 again")],
    )
    assert second.mentioned == 1
    stored = repo.get(first.id)
    assert stored is not None
    assert stored.state is ItemState.DONE
    assert len(stored.mentions) == 2
