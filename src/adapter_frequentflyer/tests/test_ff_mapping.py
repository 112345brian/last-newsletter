from __future__ import annotations

import copy
from datetime import UTC, datetime
from datetime import time as clock
from typing import cast

import pytest
from ff_fakes import fixture

from last_newsletter_adapter_frequentflyer.mapping import candidate_from_event
from last_newsletter_core.event_rules import validate_candidate
from last_newsletter_core.events import EntityRole, EventCandidate, EventDraft

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _raw(event_id: str) -> dict[str, object]:
    events = cast("list[dict[str, object]]", fixture("events.json")["events"])
    return next(e for e in events if e["id"] == event_id)


def _map(raw: dict[str, object]) -> EventCandidate:
    outcome = candidate_from_event(raw, now=_NOW, city="Los Angeles")
    assert isinstance(outcome, EventCandidate), outcome
    return outcome


def test_a_normal_event_carries_the_api_identity_and_facts() -> None:
    c = _map(_raw("ff-001"))
    assert (c.uid, c.message_id) == ("frequentflyer:ff-001", "frequentflyer:ff-001")
    assert c.url == "https://tickets.example.com/e/1"
    assert c.title == "Synthetic Band Night"
    assert c.city == "Los Angeles"
    assert c.price == "$25"
    assert c.summary == "Doors at 7."
    assert c.tags == frozenset({"music", "staff pick"})
    assert c.sequence == int(_NOW.timestamp())
    assert c.when is not None
    assert (c.when.year, c.when.month, c.when.day) == (2026, 11, 20)
    assert (c.when.time, c.when.end_time) == (clock(20, 0), clock(23, 0))
    assert c.when.tz == "America/Los_Angeles"
    assert [(e.name, e.role) for e in c.entities] == [("The Echo", EntityRole.VENUE)]


def test_a_listing_without_a_time_stays_date_only() -> None:
    c = _map(_raw("ff-002"))
    assert c.when is not None
    assert (c.when.time, c.when.end_time) == (None, None)
    assert "time tbd" in c.evidence


def test_with_no_ticket_link_the_guides_own_page_is_the_url() -> None:
    assert _map(_raw("ff-002")).url == "https://frequentflyerla.com/events/ff-002"


def test_sold_out_is_a_tag_not_a_reason_to_drop_the_event() -> None:
    assert "sold out" in _map(_raw("ff-003")).tags


def test_a_missing_venue_still_makes_a_dated_candidate() -> None:
    c = _map(_raw("ff-004"))
    assert [e for e in c.entities if e.role is EntityRole.VENUE] == []


def test_a_bad_date_is_skipped_with_a_reason() -> None:
    assert candidate_from_event(_raw("ff-005"), now=_NOW) == "bad_date"


@pytest.mark.parametrize(("field", "reason"), [("id", "no_id"), ("title", "no_title")])
def test_an_event_without_an_id_or_title_is_skipped(field: str, reason: str) -> None:
    raw = copy.deepcopy(_raw("ff-001"))
    raw[field] = "  "
    assert candidate_from_event(raw, now=_NOW) == reason


def test_a_long_description_is_cut_and_control_characters_are_neutralised() -> None:
    raw = copy.deepcopy(_raw("ff-001"))
    raw["title"] = "Band\x00 Night"
    raw["description"] = "x" * 1000
    c = _map(raw)
    assert c.title == "Band  Night"
    assert len(c.summary) == 280


def test_evidence_is_stable_for_unchanged_facts_and_changes_with_a_reschedule() -> None:
    first, again = _map(_raw("ff-001")), _map(_raw("ff-001"))
    assert first.evidence == again.evidence
    moved = copy.deepcopy(_raw("ff-001"))
    moved["date"] = "2026-11-27"
    assert _map(moved).evidence != first.evidence
    later = copy.deepcopy(_raw("ff-001"))
    later["start_time"] = "21:00"
    assert _map(later).evidence != first.evidence


def test_a_mapped_candidate_passes_core_validation_unchanged() -> None:
    draft = validate_candidate(
        _map(_raw("ff-001")),
        message_body="",
        now=_NOW,
        home_tz="America/Los_Angeles",
        check_evidence=False,
    )
    assert isinstance(draft, EventDraft)
    assert draft.venue == "The Echo"
    assert draft.uid == "frequentflyer:ff-001"
