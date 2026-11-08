"""Cross-email citation (synthetic lines only): two emails listing one film schedule under
differently worded titles are one event per date, cited twice, not two UUIDs."""

from dataclasses import replace
from datetime import UTC, datetime, time

from event_fakes import InMemoryEventRepository, ScriptedExtractor, ScriptedReader, SequentialIds

from last_newsletter_core.event_identity import IdentityPolicy, identify
from last_newsletter_core.event_rules import validate_candidate
from last_newsletter_core.event_similarity import DifflibSimilarEventIndex
from last_newsletter_core.events import (
    EntityRef,
    EntityRole,
    EventCandidate,
    EventDraft,
    MatchRule,
    PartialWhen,
)
from last_newsletter_core.use_cases import IngestEvents, IngestPorts, IngestResult
from ranked_digest.entities import EmailMessage

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_SHORT = "La bola negra"
_LONG = "La Bola Negra screening at The Frida Cinema"
_FRIDA = (EntityRef(name="The Frida Cinema", role=EntityRole.VENUE),)


def _line(day: int, weekday: str, times: str) -> str:
    return f"{weekday}, November {day}th - {times}"


def _when(day: int, *times: time) -> PartialWhen:
    return PartialWhen(
        year=2026,
        month=11,
        day=day,
        time=times[0],
        showtimes=times if len(times) > 1 else (),
        raw_text=f"November {day}",
    )


def _candidate(
    message_id: str,
    title: str,
    day: int,
    *times: time,
    venue: bool = False,
) -> EventCandidate:
    evidence = _line(day, "Monday", "12:30PM, 4PM")
    return EventCandidate(
        message_id=message_id,
        title=title,
        when=_when(day, *times),
        evidence=evidence,
        entities=_FRIDA if venue else (),
    )


def _message(message_id: str, *days: int) -> EmailMessage:
    body = "\n".join(_line(d, "Monday", "12:30PM, 4PM") for d in days)
    return EmailMessage(
        message_id=message_id,
        sender="promo@example.com",
        subject="Film listings",
        received_at=datetime(2026, 11, 5, tzinfo=UTC),
        body_text=body,
        source_label="promoter",
    )


def _run(
    repo: InMemoryEventRepository, message_id: str, candidates: list[EventCandidate], *days: int
) -> IngestResult:
    ports = IngestPorts(
        repository=repo,
        reader=ScriptedReader(),
        extractor=ScriptedExtractor(candidates),
        ids=SequentialIds(start=len(repo.events) + 1),
        similar_index=DifflibSimilarEventIndex(),
    )
    use_case = IngestEvents(ports, home_tz="America/Los_Angeles", policy=IdentityPolicy())
    return use_case.ingest([_message(message_id, *days)], now=_NOW)


def to_draft(candidate: EventCandidate) -> EventDraft:
    draft = validate_candidate(
        candidate,
        message_body=_message("x", 13, 16).body_text,
        now=_NOW,
        home_tz="America/Los_Angeles",
        check_evidence=True,
    )
    assert isinstance(draft, EventDraft)
    return draft


_T1230, _T4PM, _T8PM, _T9PM = time(12, 30), time(16), time(20), time(21)


def test_same_date_title_contained_and_same_showtimes_cites_the_first_event() -> None:
    repo = InMemoryEventRepository()
    _run(repo, "m1", [_candidate("m1", _SHORT, 16, _T1230, _T4PM)], 16)
    result = _run(repo, "m2", [_candidate("m2", _LONG, 16, _T1230, _T4PM, venue=True)], 16)
    assert (result.created, result.mentioned) == (0, 1)
    (event,) = repo.events.values()
    assert [m.message_id for m in event.mentions] == ["m1", "m2"]
    assert event.mentions[-1].match_rule is MatchRule.SAME_DATE_TITLE_CONTAINS
    assert event.mentions[-1].cited_event_id == event.id


def test_containment_is_case_insensitive_in_both_directions() -> None:
    repo = InMemoryEventRepository()
    _run(repo, "m1", [_candidate("m1", _LONG, 16, _T1230, _T4PM, venue=True)], 16)
    result = _run(repo, "m2", [_candidate("m2", "LA BOLA NEGRA", 16, _T1230, _T4PM)], 16)
    assert (result.created, result.mentioned) == (0, 1)


def test_overlapping_showtimes_are_enough() -> None:
    repo = InMemoryEventRepository()
    _run(repo, "m1", [_candidate("m1", _SHORT, 16, _T1230, _T4PM)], 16)
    result = _run(repo, "m2", [_candidate("m2", _LONG, 16, _T4PM, _T8PM, venue=True)], 16)
    assert (result.created, result.mentioned) == (0, 1)


def test_a_single_listed_time_on_both_sides_matches() -> None:
    repo = InMemoryEventRepository()
    _run(repo, "m1", [_candidate("m1", _SHORT, 16, _T4PM)], 16)
    result = _run(repo, "m2", [_candidate("m2", _LONG, 16, _T4PM, venue=True)], 16)
    assert (result.created, result.mentioned) == (0, 1)


def test_near_match_title_same_date_and_showtime_is_cited_with_its_own_rule() -> None:
    repo = InMemoryEventRepository()
    _run(repo, "m1", [_candidate("m1", "La Bola Negra", 16, _T1230, _T4PM)], 16)
    result = _run(repo, "m2", [_candidate("m2", "La Bola Negrra", 16, _T1230, _T4PM)], 16)
    assert (result.created, result.mentioned) == (0, 1)
    (event,) = repo.events.values()
    assert event.mentions[-1].match_rule in {
        MatchRule.SAME_DATE_TITLE_CONTAINS,
        MatchRule.SAME_DATE_TITLE_SIMILAR,
    }


def test_disjoint_showtimes_on_one_date_are_not_merged() -> None:
    repo = InMemoryEventRepository()
    _run(repo, "m1", [_candidate("m1", _SHORT, 16, _T1230, _T4PM)], 16)
    result = _run(repo, "m2", [_candidate("m2", _LONG, 16, _T8PM, _T9PM, venue=True)], 16)
    assert (result.created, result.mentioned) == (1, 0)


def test_two_different_venues_are_not_merged() -> None:
    repo = InMemoryEventRepository()
    other = (EntityRef(name="Some Other Hall", role=EntityRole.VENUE),)
    first = replace(_candidate("m1", _SHORT, 16, _T1230, _T4PM), entities=other)
    _run(repo, "m1", [first], 16)
    result = _run(repo, "m2", [_candidate("m2", _LONG, 16, _T1230, _T4PM, venue=True)], 16)
    assert (result.created, result.mentioned) == (1, 0)


def test_two_fitting_same_date_events_stay_separate_and_linked_both_ways() -> None:
    repo = InMemoryEventRepository()
    for n, hall in enumerate(("Hall X", "Hall Y"), start=1):
        venue = (EntityRef(name=hall, role=EntityRole.VENUE),)
        draft = replace(_candidate(f"m{n}", _SHORT, 16, _T1230, _T4PM), entities=venue)
        _run(repo, f"m{n}", [draft], 16)
    before = set(repo.events)
    assert len(before) == 2
    result = _run(repo, "m3", [_candidate("m3", _LONG, 16, _T1230, _T4PM)], 16)
    assert (result.created, result.mentioned, result.possible_duplicates) == (1, 0, 1)
    (new_id,) = set(repo.events) - before
    assert set(repo.events[new_id].possible_duplicates) == before
    assert all(new_id in repo.events[i].possible_duplicates for i in before)


def test_the_same_series_on_three_dates_is_three_events_with_two_mentions_and_no_links() -> None:
    repo = InMemoryEventRepository()
    days = (13, 16, 17)
    _run(repo, "m1", [_candidate("m1", _SHORT, d, _T1230, _T4PM) for d in days], *days)
    result = _run(
        repo, "m2", [_candidate("m2", _LONG, d, _T1230, _T4PM, venue=True) for d in days], *days
    )
    assert (result.created, result.mentioned) == (0, 3)
    assert len(repo.events) == 3
    assert all(len(e.mentions) == 2 for e in repo.events.values())
    assert all(e.possible_duplicates == () for e in repo.events.values())


def test_different_dates_of_a_series_are_never_possible_duplicates() -> None:
    """Even when the titles differ and nothing matches, other dates are not duplicates."""
    repo = InMemoryEventRepository()
    result = _run(
        repo,
        "m1",
        [
            _candidate("m1", _SHORT, 13, _T1230, _T4PM),
            _candidate("m1", _LONG, 16, _T1230, _T4PM, venue=True),
            _candidate("m1", "La bola negra at the Frida", 17, _T1230, _T4PM),
        ],
        13,
        16,
        17,
    )
    assert (result.created, result.possible_duplicates) == (3, 0)
    assert all(e.possible_duplicates == () for e in repo.events.values())


def test_a_similarity_hit_or_shared_url_on_another_date_is_not_a_possible_duplicate() -> None:
    """The scores the index returns ignore dates; identity must not turn them into links."""
    repo = InMemoryEventRepository()
    _run(repo, "m1", [_candidate("m1", _SHORT, 13, _T1230, _T4PM)], 13)
    (other,) = repo.events.values()
    draft = to_draft(_candidate("m2", _SHORT, 16, _T1230, _T4PM, venue=True))
    url = replace(other, url="https://example.com/films/la-bola-negra")
    decision = identify(
        replace(draft, url=url.url), [url], similar=lambda: [(url, 0.9)], policy=IdentityPolicy()
    )
    assert (decision.rule, decision.event, decision.possible_duplicates) == (
        MatchRule.NEW,
        None,
        (),
    )
