from __future__ import annotations

from datetime import UTC, datetime
from datetime import time as clock
from zoneinfo import ZoneInfo

import pytest
from ical_fakes import vevent

from last_newsletter_adapter_ical import venue_from_location
from last_newsletter_adapter_ical.mapping import candidate_from_vevent
from last_newsletter_core.event_rules import validate_candidate
from last_newsletter_core.events import EntityRole, EventCandidate, EventDraft

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_LA = ZoneInfo("America/Los_Angeles")
_BASE = ["UID:abc-1@example.com", "SUMMARY:Mdou Moctar", "DTSTART:20261121T040000Z"]


def _map(lines: list[str], *, venue: str = "") -> EventCandidate:
    outcome = candidate_from_vevent(vevent(lines), name="feed", tz=_LA, now=_NOW, venue=venue)
    assert isinstance(outcome, EventCandidate), outcome
    return outcome


def _skip(lines: list[str]) -> str:
    outcome = candidate_from_vevent(vevent(lines), name="feed", tz=_LA, now=_NOW)
    assert isinstance(outcome, str), outcome
    return outcome


def test_the_feeds_own_uid_is_the_identity_and_the_message_is_namespaced_by_source() -> None:
    c = _map(_BASE)
    assert c.uid == "abc-1@example.com"
    assert c.message_id == "feed:abc-1@example.com"


def test_a_utc_time_is_shown_in_the_feeds_zone_and_can_change_the_date() -> None:
    c = _map(_BASE)  # 04:00Z on the 21st is 8pm on the 20th in Los Angeles
    assert c.when is not None
    assert (c.when.year, c.when.month, c.when.day) == (2026, 11, 20)
    assert c.when.time == clock(20, 0)
    assert c.when.tz == "America/Los_Angeles"


def test_a_time_with_its_own_zone_is_converted_to_the_feeds_zone() -> None:
    c = _map(["UID:a", "SUMMARY:S", "DTSTART;TZID=America/New_York:20261120T230000"])
    assert c.when is not None
    assert (c.when.day, c.when.time) == (20, clock(20, 0))


def test_a_floating_time_is_taken_to_be_in_the_feeds_zone() -> None:
    c = _map(["UID:a", "SUMMARY:S", "DTSTART:20261120T203000"])
    assert c.when is not None
    assert (c.when.day, c.when.time) == (20, clock(20, 30))


def test_an_all_day_event_has_a_date_and_no_time() -> None:
    c = _map(["UID:a", "SUMMARY:S", "DTSTART;VALUE=DATE:20261120", "DTEND;VALUE=DATE:20261121"])
    assert c.when is not None
    assert (c.when.day, c.when.time) == (20, None)
    assert "time tbd" in c.evidence


def test_an_all_day_span_of_several_days_is_skipped_and_counted() -> None:
    lines = ["UID:a", "SUMMARY:S", "DTSTART;VALUE=DATE:20261010", "DTEND;VALUE=DATE:20261213"]
    assert _skip(lines) == "multi_day"


def test_an_end_within_a_day_becomes_the_end_time_and_a_longer_one_does_not() -> None:
    short = _map([*_BASE, "DTEND:20261121T070000Z"])
    assert short.when is not None
    assert short.when.end_time == clock(23, 0)
    long = _map([*_BASE, "DTEND:20261123T040000Z"])
    assert long.when is not None
    assert long.when.end_time is None


@pytest.mark.parametrize(
    ("lines", "reason"),
    [
        (["SUMMARY:S", "DTSTART:20261121T040000Z"], "no_uid"),
        (["UID:a", "DTSTART:20261121T040000Z"], "no_title"),
        (["UID:a", "SUMMARY:S"], "no_date"),
        (["UID:a", "SUMMARY:S", "DTSTART:20261121T040000Z", "STATUS:CANCELLED"], "cancelled"),
        (["UID:a", "SUMMARY:S", "DTSTART:20261121T040000Z", "RRULE:FREQ=WEEKLY"], "recurring"),
    ],
)
def test_events_that_cannot_be_used_are_skipped_with_a_reason(
    lines: list[str], reason: str
) -> None:
    assert _skip(lines) == reason


def test_one_instance_of_a_series_gets_its_own_identity() -> None:
    c = _map([*_BASE, "RECURRENCE-ID:20261114T040000Z"])
    assert c.uid is not None
    assert c.uid.startswith("abc-1@example.com#")


def test_a_sequence_in_the_feed_is_used_otherwise_the_fetch_time() -> None:
    assert _map([*_BASE, "SEQUENCE:7"]).sequence == 7
    assert _map(_BASE).sequence == int(_NOW.timestamp())


def test_escapes_and_folded_lines_are_undone() -> None:
    lines = [
        "UID:a",
        "SUMMARY:Band A\\, Band B\\; folded in the mid",
        " dle of a word",
        "DTSTART:20261121T040000Z",
    ]
    assert _map(lines).title == "Band A, Band B; folded in the middle of a word"


def test_categories_become_tags_and_html_in_the_description_is_removed_and_cut() -> None:
    c = _map([*_BASE, "CATEGORIES:Music,Free", f"DESCRIPTION:<p>Doors <b>7pm</b></p>{'x' * 400}"])
    assert c.tags == frozenset({"music", "free"})
    assert c.summary.startswith("Doors 7pm")
    assert "<" not in c.summary
    assert len(c.summary) == 280


@pytest.mark.parametrize(
    ("location", "venue"),
    [
        ("The Mayan, 1038 S Hill St, Los Angeles, CA 90015", "The Mayan"),
        ("Globe Theatre", "Globe Theatre"),
        ("Pantages Theatre, 6233 Hollywood Boulevard, Los Angeles", "Pantages Theatre"),
        ("Location   Thorne Hall [/locations/thorne-hall]", "Thorne Hall"),
        ("Pomona, CA", ""),
        ("Los Angeles, CA 90015", ""),
        ("1038 S Hill St, Los Angeles", ""),
        ("", ""),
    ],
)
def test_a_venue_is_guessed_from_a_location_only_when_it_looks_like_one(
    location: str, venue: str
) -> None:
    assert venue_from_location(location) == venue


def test_a_configured_venue_beats_the_guess_and_is_a_venue_entity() -> None:
    c = _map([*_BASE, "LOCATION:Pomona\\, CA"], venue="The Smell")
    assert [(e.name, e.role) for e in c.entities] == [("The Smell", EntityRole.VENUE)]


def test_evidence_is_stable_for_unchanged_facts_and_changes_with_a_move() -> None:
    first, again = (
        _map([*_BASE, "LOCATION:Globe Theatre"]),
        _map([*_BASE, "LOCATION:Globe Theatre"]),
    )
    assert first.evidence == again.evidence
    later = _map(["UID:abc-1@example.com", "SUMMARY:Mdou Moctar", "DTSTART:20261122T040000Z"])
    assert later.evidence != first.evidence
    moved = _map([*_BASE, "LOCATION:Another Room"])
    assert moved.evidence != first.evidence


def test_a_mapped_candidate_passes_core_validation_unchanged() -> None:
    draft = validate_candidate(
        _map([*_BASE, "LOCATION:Globe Theatre, 1 Main St, Los Angeles"]),
        message_body="",
        now=_NOW,
        home_tz="America/Los_Angeles",
        check_evidence=False,
    )
    assert isinstance(draft, EventDraft)
    assert draft.venue == "Globe Theatre"
    assert draft.uid == "abc-1@example.com"
