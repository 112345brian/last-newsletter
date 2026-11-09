from __future__ import annotations

from datetime import UTC, datetime
from datetime import time as clock
from zoneinfo import ZoneInfo

import pytest
from ss_fakes import item, ms, para

from last_newsletter_adapter_squarespace import is_date_like
from last_newsletter_adapter_squarespace.mapping import FeedContext, candidate_from_item
from last_newsletter_core.event_rules import validate_candidate
from last_newsletter_core.events import EntityRole, EventCandidate, EventDraft

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_LA = ZoneInfo("America/Los_Angeles")
_BASE = "https://www.venue.example"


def _feed(venue: str = "The Smell", organizer: str = "") -> FeedContext:
    return FeedContext("smell", _BASE, _LA, _NOW, venue=venue, organizer=organizer)


def _map(raw: dict[str, object], feed: FeedContext | None = None) -> EventCandidate:
    outcome = candidate_from_item(raw, feed or _feed())
    assert isinstance(outcome, EventCandidate), outcome
    return outcome


_DATED = item(
    excerpt=para(
        "Alberto Marquez Productions presents…",
        "Sikaflanta",
        "weresorrybutsomethingwentwrong",
        "9:00 pm",
        "$10 in advance, $15 at the door",
        '<a href="https://tickets.example.com/e/9">Advance tickets available here.</a>',
    ),
    tags=["Sikaflanta", "weresorrybutsomethingwentwrong", "Thursday November 12 2026"],
)


def test_a_date_titled_event_is_named_for_its_lineup_from_the_tags() -> None:
    c = _map(_DATED)
    assert c.title == "Sikaflanta / weresorrybutsomethingwentwrong"
    assert c.tags == frozenset()
    assert c.uid == c.message_id == "smell:abc1"


def test_the_instant_is_shown_in_the_feeds_zone_and_the_default_end_is_ignored() -> None:
    c = _map(_DATED)
    assert c.when is not None
    assert (c.when.year, c.when.month, c.when.day) == (2026, 11, 12)
    assert (c.when.time, c.when.end_time, c.when.tz) == (clock(20, 0), None, "America/Los_Angeles")


def test_a_midnight_crossing_in_utc_still_lands_on_the_local_date() -> None:
    c = _map(item(start=ms(2026, 11, 12, 23, 30)))  # 07:30Z on the 13th
    assert c.when is not None
    assert (c.when.day, c.when.time) == (12, clock(23, 30))


def test_the_promoter_line_names_an_organizer_the_room_stays_the_venue() -> None:
    roles = {(e.name, e.role) for e in _map(_DATED).entities}
    assert roles == {
        ("The Smell", EntityRole.VENUE),
        ("Alberto Marquez Productions", EntityRole.ORGANIZER),
    }


def test_the_price_and_the_ticket_link_come_from_the_excerpt() -> None:
    c = _map(_DATED)
    assert c.price == "$10 in advance, $15 at the door"
    assert c.url == "https://tickets.example.com/e/9"


def test_without_a_ticket_link_the_pages_own_address_is_the_url() -> None:
    c = _map(item(excerpt=para("Band A"), tags=["Band A"]))
    assert c.url == f"{_BASE}/events/thursday-november-12-2026"


def test_the_lineup_falls_back_to_the_excerpt_when_the_tags_hold_only_the_date() -> None:
    raw = item(
        excerpt=para("Band A", "Band B", "8:00 pm", "$10"), tags=["Thursday November 12 2026"]
    )
    assert _map(raw).title == "Band A / Band B"


def test_a_promoter_named_in_the_tags_is_not_listed_as_a_band() -> None:
    raw = item(
        excerpt=para("Lumea Magazine presents…", "Kim Theory", "Astatine", "8:00 pm"),
        tags=["Kim Theory", "Astatine", "Lumea Magazine", "Friday November 20 2026"],
    )
    c = _map(raw)
    assert c.title == "Kim Theory / Astatine"
    assert ("Lumea Magazine", EntityRole.ORGANIZER) in {(e.name, e.role) for e in c.entities}


def test_invisible_characters_in_a_lineup_are_cleaned() -> None:
    raw = item(
        tags=[
            "Skidwizard\N{ZERO WIDTH JOINER} \N{ZERO WIDTH JOINER}(Portland, OR)",
            "Axid\N{NO-BREAK SPACE}",
        ]
    )
    assert _map(raw).title == "Skidwizard (Portland, OR) / Axid"


def test_a_real_title_is_kept_unescaped_with_the_first_line_as_summary_and_tags() -> None:
    raw = item(
        title="Anna Wise &amp; San Cha: Ginger Snow",
        excerpt=para("Bring your blanket and gather for a night of music."),
        tags=["Outdoors", "No Pets Please"],
    )
    c = _map(raw)
    assert c.title == "Anna Wise & San Cha: Ginger Snow"
    assert c.summary == "Bring your blanket and gather for a night of music."
    assert c.tags == frozenset({"outdoors", "no pets please"})


def test_a_promoters_feed_has_an_organizer_and_no_invented_venue() -> None:
    c = _map(item(title="Moonlight Hike"), _feed(venue="", organizer="Living Earth"))
    assert [(e.name, e.role) for e in c.entities] == [("Living Earth", EntityRole.ORGANIZER)]


def test_the_update_time_orders_changes_otherwise_the_fetch_time_does() -> None:
    assert _map(item(updated=1_794_000_000_000)).sequence == 1_794_000_000
    raw = item()
    del raw["updatedOn"]
    assert _map(raw).sequence == int(_NOW.timestamp())


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [("id", " ", "no_id"), ("title", " ", "no_title"), ("startDate", "soon", "no_date")],
)
def test_items_that_cannot_be_used_are_skipped_with_a_reason(
    field: str, value: str, reason: str
) -> None:
    raw = item()
    raw[field] = value
    assert candidate_from_item(raw, _feed()) == reason


def test_evidence_is_stable_for_unchanged_facts_and_changes_with_a_reschedule() -> None:
    assert _map(_DATED).evidence == _map(_DATED).evidence
    assert _map(item(start=ms(2026, 11, 13))).evidence != _map(item()).evidence
    assert _map(item(start=ms(2026, 11, 12, 21))).evidence != _map(item()).evidence


@pytest.mark.parametrize(
    "text",
    [
        "Thursday, November 12, 2026",
        "Thursday November 12 2026",
        "Sat Nov 14",
        "Friday, November 13th, 2026",
    ],
)
def test_a_date_used_as_a_name_is_recognised(text: str) -> None:
    assert is_date_like(text)


@pytest.mark.parametrize(
    "text", ["Anna Wise: An Intimate Concert", "Friday Night Moonlight Hike", "Thursday"]
)
def test_a_real_name_is_not_mistaken_for_a_date(text: str) -> None:
    assert not is_date_like(text)


def test_a_mapped_candidate_passes_core_validation_unchanged() -> None:
    draft = validate_candidate(
        _map(_DATED),
        message_body="",
        now=_NOW,
        home_tz="America/Los_Angeles",
        check_evidence=False,
    )
    assert isinstance(draft, EventDraft)
    assert draft.venue == "The Smell"
    assert draft.uid == "smell:abc1"
