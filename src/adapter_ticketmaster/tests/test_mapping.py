from __future__ import annotations

import copy
from datetime import UTC, datetime
from datetime import time as clock
from typing import cast

import pytest
from tm_fakes import fixture

from last_newsletter_adapter_ticketmaster.mapping import candidate_from_event
from last_newsletter_core.event_rules import validate_candidate
from last_newsletter_core.events import EntityRole, EventCandidate, EventDraft

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_MUSIC = frozenset({"music"})


def _raw(event_id: str) -> dict[str, object]:
    page = fixture("events_page.json")
    embedded = cast("dict[str, list[dict[str, object]]]", page["_embedded"])
    return next(e for e in embedded["events"] if e["id"] == event_id)


def _map(raw: dict[str, object]) -> EventCandidate:
    outcome = candidate_from_event(raw, now=_NOW, categories=_MUSIC)
    assert isinstance(outcome, EventCandidate), outcome
    return outcome


def test_a_normal_event_carries_the_api_identity_and_facts() -> None:
    c = _map(_raw("tm-001"))
    assert (c.uid, c.message_id) == ("ticketmaster:tm-001", "ticketmaster:tm-001")
    assert c.url == "https://www.ticketmaster.com/event/tm-001"
    assert c.title == "Mdou Moctar"
    assert c.city == "Los Angeles"
    assert c.tags == frozenset({"alternative"})  # "Undefined" sub-genre is dropped
    assert c.price == "$35-$55.5"
    assert c.sequence == int(_NOW.timestamp())
    assert c.when is not None
    assert (c.when.year, c.when.month, c.when.day) == (2026, 11, 20)
    assert c.when.time == clock(20, 0)
    assert c.when.tz == "America/Los_Angeles"


def test_first_attraction_headlines_the_rest_support_and_the_venue_is_a_venue() -> None:
    roles = [(e.name, e.role) for e in _map(_raw("tm-001")).entities]
    assert roles == [
        ("Mdou Moctar", EntityRole.HEADLINER),
        ("Fuzz Opener", EntityRole.SUPPORT),
        ("The Fonda Theatre", EntityRole.VENUE),
    ]


def test_time_tba_and_a_missing_venue_still_make_a_dated_candidate() -> None:
    c = _map(_raw("tm-004"))
    assert c.when is not None
    assert c.when.time is None
    assert [e for e in c.entities if e.role is EntityRole.VENUE] == []
    assert "time tbd" in c.evidence


def test_the_timezone_falls_back_to_the_venue_when_the_event_has_none() -> None:
    raw = copy.deepcopy(_raw("tm-001"))
    dates = cast("dict[str, object]", raw["dates"])
    del dates["timezone"]
    when = _map(raw).when
    assert when is not None
    assert when.tz == "America/Los_Angeles"


@pytest.mark.parametrize(
    ("event_id", "reason"),
    [("tm-002", "cancelled"), ("tm-003", "not_in_category"), ("tm-005", "postponed")],
)
def test_events_that_are_not_happening_or_not_music_are_skipped_with_a_reason(
    event_id: str, reason: str
) -> None:
    assert candidate_from_event(_raw(event_id), now=_NOW, categories=_MUSIC) == reason


def test_the_us_spelling_of_cancelled_is_recognised_too() -> None:
    raw = copy.deepcopy(_raw("tm-001"))
    cast("dict[str, dict[str, str]]", raw["dates"])["status"]["code"] = "cancelled"
    assert candidate_from_event(raw, now=_NOW, categories=_MUSIC) == "cancelled"


def test_an_event_with_no_date_yet_is_skipped() -> None:
    raw = copy.deepcopy(_raw("tm-001"))
    cast("dict[str, dict[str, object]]", raw["dates"])["start"] = {"dateTBD": True}
    assert candidate_from_event(raw, now=_NOW, categories=_MUSIC) == "date_tbd"


@pytest.mark.parametrize(("field", "reason"), [("id", "no_id"), ("name", "no_title")])
def test_an_event_without_an_id_or_title_is_skipped(field: str, reason: str) -> None:
    raw = copy.deepcopy(_raw("tm-001"))
    raw[field] = "  "
    assert candidate_from_event(raw, now=_NOW, categories=_MUSIC) == reason


def test_no_category_filter_keeps_every_segment() -> None:
    outcome = candidate_from_event(_raw("tm-003"), now=_NOW, categories=frozenset())
    assert isinstance(outcome, EventCandidate)


def test_control_characters_in_text_are_neutralised() -> None:
    raw = copy.deepcopy(_raw("tm-001"))
    raw["name"] = "Mdou\x00 Moctar\x07"
    raw["info"] = "Doors 7\npm"
    c = _map(raw)
    assert c.title == "Mdou  Moctar"
    assert "\x00" not in c.title + c.summary + c.evidence
    assert "\n" not in c.summary


def test_evidence_is_stable_for_unchanged_facts_and_changes_with_a_reschedule() -> None:
    first, again = _map(_raw("tm-001")), _map(_raw("tm-001"))
    assert first.evidence == again.evidence
    moved = copy.deepcopy(_raw("tm-001"))
    start = cast("dict[str, dict[str, str]]", moved["dates"])["start"]
    start["localDate"] = "2026-11-27"
    assert _map(moved).evidence != first.evidence
    later = copy.deepcopy(_raw("tm-001"))
    cast("dict[str, dict[str, str]]", later["dates"])["start"]["localTime"] = "21:00:00"
    assert _map(later).evidence != first.evidence


def test_a_mapped_candidate_passes_core_validation_unchanged() -> None:
    draft = validate_candidate(
        _map(_raw("tm-001")),
        message_body="",
        now=_NOW,
        home_tz="America/Los_Angeles",
        check_evidence=False,
    )
    assert isinstance(draft, EventDraft)
    assert draft.venue == "The Fonda Theatre"
    assert draft.uid == "ticketmaster:tm-001"
