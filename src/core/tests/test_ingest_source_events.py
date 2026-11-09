"""Structured sources go through the same ladder as mail: created once, cited when already known,
unchanged on a rerun, updated when the source reschedules, and loud when the fetch fails."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from datetime import time as clock
from uuid import UUID

import pytest
from event_fakes import InMemoryEventRepository, SequentialIds

from last_newsletter_core.event_ports import SourceFetchError, SourceQuery
from last_newsletter_core.event_rules import RejectReason
from last_newsletter_core.events import (
    AllDay,
    EntityRef,
    EntityRole,
    Event,
    EventCandidate,
    EventId,
    EventKind,
    MatchRule,
    Mention,
    PartialWhen,
    Timed,
    local_date,
)
from last_newsletter_core.use_cases import IngestSourceEvents, SourceIngestPorts

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_QUERY = SourceQuery(city="Los Angeles", date_from=date(2026, 11, 6), date_to=date(2026, 12, 31))
_TZ = "America/Los_Angeles"


def _candidate(
    source_id: str = "1",
    *,
    title: str = "Mdou Moctar",
    day: tuple[int, int, int] = (2026, 11, 20),
    venue: str | None = "The Fonda Theatre",
    sequence: int = 1,
) -> EventCandidate:
    year, month, number = day
    entities = (EntityRef(name=venue, role=EntityRole.VENUE),) if venue is not None else ()
    return EventCandidate(
        message_id=f"fake:{source_id}",
        title=title,
        kind=EventKind.EVENT,
        when=PartialWhen(year=year, month=month, day=number, time=clock(20), tz=_TZ),
        evidence=f"fake {source_id} | {title} | {year}-{month:02d}-{number:02d} | {venue}",
        entities=entities,
        uid=f"fake:{source_id}",
        url=f"https://tickets.example.com/event/{source_id}",
        sequence=sequence,
    )


@dataclass
class FakeSource:
    candidates: list[EventCandidate] = field(default_factory=list)
    error: SourceFetchError | None = None
    calls: int = 0

    @property
    def name(self) -> str:
        return "fake"

    def fetch(self, query: SourceQuery, *, now: datetime) -> list[EventCandidate]:
        _ = (query, now)
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.candidates)


def _use_case(source: FakeSource, repo: InMemoryEventRepository) -> IngestSourceEvents:
    ports = SourceIngestPorts(repository=repo, ids=SequentialIds(start=len(repo.events) + 1))
    return IngestSourceEvents(source, ports, home_tz=_TZ)


def test_new_source_events_are_created_with_the_source_as_provenance() -> None:
    repo = InMemoryEventRepository()
    source = FakeSource([_candidate("1"), _candidate("2", title="Dub Club", venue="Zebulon")])
    result = _use_case(source, repo).ingest(_QUERY, now=_NOW)
    assert (result.created, result.mentioned, result.unchanged) == (2, 0, 0)
    first = next(e for e in repo.events.values() if e.title == "Mdou Moctar")
    assert first.uid == "fake:1"
    assert first.url == "https://tickets.example.com/event/1"
    assert first.venue == "The Fonda Theatre"
    assert [m.source for m in first.mentions] == ["fake"]
    assert isinstance(first.when, Timed)
    assert first.when.tz_name == _TZ


def test_a_rerun_changes_nothing() -> None:
    repo = InMemoryEventRepository()
    source = FakeSource([_candidate("1"), _candidate("2", title="Dub Club", venue="Zebulon")])
    first = _use_case(source, repo).ingest(_QUERY, now=_NOW)
    assert first.created == 2
    again = _use_case(source, repo).ingest(_QUERY, now=_NOW)
    assert (again.created, again.mentioned, again.unchanged) == (0, 0, 2)
    assert len(repo.events) == 2
    assert all(len(e.mentions) == 1 for e in repo.events.values())


def _seed_mail_event(repo: InMemoryEventRepository) -> EventId:
    seen = datetime(2026, 11, 1, tzinfo=UTC)
    known = EventId(UUID(int=99))
    repo.upsert(
        Event(
            id=known,
            kind=EventKind.EVENT,
            title="mdou moctar",
            summary="",
            when=AllDay(date(2026, 11, 20)),
            entities=(EntityRef(name="the fonda theatre", role=EntityRole.VENUE),),
            mentions=(
                Mention(
                    message_id="mail-1",
                    seen_at=seen,
                    source="venue newsletter",
                    evidence="Fri Nov 20 Mdou Moctar",
                    match_rule=MatchRule.NEW,
                    cited_event_id=known,
                ),
            ),
            first_seen=seen,
            last_seen=seen,
        )
    )
    return known


def test_an_event_already_known_from_mail_is_cited_not_duplicated() -> None:
    repo = InMemoryEventRepository()
    _seed_mail_event(repo)
    result = _use_case(FakeSource([_candidate("1")]), repo).ingest(_QUERY, now=_NOW)
    assert (result.created, result.mentioned) == (0, 1)
    (event,) = repo.events.values()
    assert [m.source for m in event.mentions] == ["venue newsletter", "fake"]
    assert event.mentions[-1].match_rule is MatchRule.TITLE_DATE_VENUE
    # The email-derived facts are not overwritten by a citation.
    assert event.title == "mdou moctar"
    assert local_date(event.when) == date(2026, 11, 20)


def test_a_rerun_after_citing_a_mail_event_is_unchanged() -> None:
    repo = InMemoryEventRepository()
    _seed_mail_event(repo)
    source = FakeSource([_candidate("1")])
    first = _use_case(source, repo).ingest(_QUERY, now=_NOW)
    assert first.mentioned == 1
    again = _use_case(source, repo).ingest(_QUERY, now=_NOW)
    assert (again.created, again.mentioned, again.unchanged) == (0, 0, 1)
    (event,) = repo.events.values()
    assert len(event.mentions) == 2


def test_a_rescheduled_event_updates_the_same_event() -> None:
    repo = InMemoryEventRepository()
    seeded = _use_case(FakeSource([_candidate("1", sequence=1)]), repo).ingest(_QUERY, now=_NOW)
    assert seeded.created == 1
    moved = _candidate("1", day=(2026, 11, 27), sequence=2)
    result = _use_case(FakeSource([moved]), repo).ingest(_QUERY, now=_NOW)
    assert (result.created, result.mentioned) == (0, 1)
    (event,) = repo.events.values()
    assert local_date(event.when) == date(2026, 11, 27)
    assert event.sequence == 2
    assert len(event.mentions) == 2


def test_the_same_title_on_another_date_is_a_separate_event() -> None:
    repo = InMemoryEventRepository()
    source = FakeSource([_candidate("1", day=(2026, 11, 20)), _candidate("2", day=(2026, 11, 21))])
    result = _use_case(source, repo).ingest(_QUERY, now=_NOW)
    assert (result.created, result.mentioned) == (2, 0)


def test_a_past_event_is_rejected_and_counted_never_dropped_silently() -> None:
    repo = InMemoryEventRepository()
    result = _use_case(FakeSource([_candidate("1", day=(2026, 10, 1))]), repo).ingest(
        _QUERY, now=_NOW
    )
    assert result.created == 0
    assert result.rejected == {RejectReason.PAST_DATE: 1}


def test_a_source_candidate_without_a_venue_is_still_ingested() -> None:
    repo = InMemoryEventRepository()
    result = _use_case(FakeSource([_candidate("1", venue=None)]), repo).ingest(_QUERY, now=_NOW)
    assert result.created == 1
    assert next(iter(repo.events.values())).venue == ""


def test_a_failed_fetch_propagates_and_writes_nothing() -> None:
    repo = InMemoryEventRepository()
    source = FakeSource(error=SourceFetchError("quota exhausted"))
    with pytest.raises(SourceFetchError, match="quota exhausted"):
        _ = _use_case(source, repo).ingest(_QUERY, now=_NOW)
    assert repo.events == {}


def test_an_empty_fetch_is_a_quiet_success() -> None:
    result = _use_case(FakeSource(), InMemoryEventRepository()).ingest(_QUERY, now=_NOW)
    assert (result.created, result.mentioned, result.unchanged) == (0, 0, 0)
