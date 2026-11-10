from __future__ import annotations

from datetime import UTC, date, datetime
from datetime import time as clock
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx
import pytest
from venue_fakes import Handled, show

from last_newsletter_adapter_venues import JsonClient, LodgeRoomConfig, LodgeRoomEventSource
from last_newsletter_adapter_venues.lodgeroom import candidate_from_show
from last_newsletter_core.event_ports import EventSource, SourceFetchError, SourceWindow
from last_newsletter_core.event_rules import validate_candidate
from last_newsletter_core.events import EntityRole, EventCandidate, EventDraft

if TYPE_CHECKING:
    from collections.abc import Callable

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_LA = ZoneInfo("America/Los_Angeles")
_WINDOW = SourceWindow(date_from=date(2026, 11, 10), date_to=date(2026, 11, 30))


def _map(raw: dict[str, object]) -> EventCandidate:
    outcome = candidate_from_show(raw, name="lodgeroom", tz=_LA, now=_NOW)
    assert isinstance(outcome, EventCandidate), outcome
    return outcome


def test_a_show_carries_its_identity_time_and_people() -> None:
    c = _map(show(101, headliners=["Mdou Moctar"], supports=["Opener A", "Opener B"]))
    assert c.uid == c.message_id == "lodgeroom:101"
    assert c.title == "Mdou Moctar"
    assert c.url == "https://www.lodgeroomhlp.com/shows/show-101/"
    assert c.when is not None
    assert (c.when.year, c.when.month, c.when.day) == (2026, 11, 20)
    assert (c.when.time, c.when.tz) == (clock(20, 0), "America/Los_Angeles")
    assert [(e.name, e.role) for e in c.entities] == [
        ("Mdou Moctar", EntityRole.HEADLINER),
        ("Opener A", EntityRole.SUPPORT),
        ("Opener B", EntityRole.SUPPORT),
        ("Lodge Room", EntityRole.VENUE),
    ]
    assert c.age == "ALL AGES"
    assert c.summary == "Doors 7:00 pm. An evening of desert blues ."


def test_the_date_comes_from_the_show_field_never_the_publish_date() -> None:
    raw = show(when="01/06/2027 9:30 pm")
    raw["date"] = "2026-11-04T10:00:00"  # the listing's publish date: must be ignored
    c = _map(raw)
    assert c.when is not None
    assert (c.when.year, c.when.month, c.when.day, c.when.time) == (2027, 1, 6, clock(21, 30))


def test_a_listing_with_only_a_date_has_no_time() -> None:
    c = _map(show(when="11/20/2026"))
    assert c.when is not None
    assert c.when.time is None
    assert "time tbd" in c.evidence


def test_a_ticket_or_rsvp_link_beats_the_shows_own_page() -> None:
    assert _map(show(external_ticket_button_url="https://tix.example.com/1")).url == (
        "https://tix.example.com/1"
    )
    assert _map(show(rsvp_url="https://rsvp.example.com/1")).url == "https://rsvp.example.com/1"


def test_wordpress_entities_in_a_title_are_decoded() -> None:
    assert _map(show(title="Nick Cave &amp; The Bad Seeds&#8217; Night")).title == (
        "Nick Cave & The Bad Seeds\u2019 Night"
    )


def test_an_empty_title_falls_back_to_the_headliners() -> None:
    assert _map(show(title="", headliners=["A", "B"])).title == "A / B"


def test_genre_becomes_a_tag_and_the_update_time_the_sequence() -> None:
    c = _map(show(genre="Indie Rock"))
    assert c.tags == frozenset({"indie rock"})
    assert c.sequence == int(datetime(2026, 11, 4, 22, 23, 9, tzinfo=UTC).timestamp())


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"id": ""}, "no_id"),
        (
            {"title": {"rendered": ""}, "acf": {"headliner": "", "date_and_time_of_show": "x"}},
            "no_title",
        ),
        ({"acf": {"headliner": [], "date_and_time_of_show": "soon"}}, "bad_date"),
    ],
)
def test_shows_that_cannot_be_used_are_skipped_with_a_reason(
    change: dict[str, object], reason: str
) -> None:
    raw = show(title="x") | change
    assert candidate_from_show(raw, name="lodgeroom", tz=_LA, now=_NOW) == reason


def test_evidence_is_stable_for_unchanged_facts_and_changes_with_a_reschedule() -> None:
    assert _map(show()).evidence == _map(show()).evidence
    assert _map(show(when="11/21/2026 8:00 pm")).evidence != _map(show()).evidence
    assert _map(show(when="11/20/2026 9:00 pm")).evidence != _map(show()).evidence


def test_a_mapped_candidate_passes_core_validation_unchanged() -> None:
    draft = validate_candidate(
        _map(show()), message_body="", now=_NOW, home_tz="America/Los_Angeles", check_evidence=False
    )
    assert isinstance(draft, EventDraft)
    assert draft.venue == "Lodge Room"


def _pages(pages: list[list[dict[str, object]]]) -> Callable[[dict[str, str]], httpx.Response]:
    def handler(params: dict[str, str]) -> httpx.Response:
        number = int(params["page"])
        return httpx.Response(
            200, json=pages[number - 1], headers={"X-WP-TotalPages": str(len(pages))}
        )

    return handler


def _source(handled: Handled, sleeps: list[float] | None = None) -> LodgeRoomEventSource:
    pauses = sleeps if sleeps is not None else []
    return LodgeRoomEventSource(JsonClient(http=handled.client), sleep=pauses.append)


def test_it_is_an_event_source_named_after_the_venue() -> None:
    source: EventSource = _source(Handled(_pages([[]])))
    assert source.name == "lodgeroom"


def test_every_page_is_read_because_the_feed_is_not_ordered_by_show_date() -> None:
    pages = [[show(1, when="11/12/2026 8:00 pm")], [show(2, when="11/14/2026 8:00 pm")], [show(3)]]
    handled = Handled(_pages(pages))
    sleeps: list[float] = []
    batch = _source(handled, sleeps).fetch(_WINDOW, now=_NOW)
    assert [c.uid for c in batch.candidates] == ["lodgeroom:1", "lodgeroom:2", "lodgeroom:3"]
    assert [q["page"] for q in handled.queries] == ["1", "2", "3"]
    assert handled.queries[0]["_fields"] == "id,link,title,acf,modified_gmt"
    assert handled.queries[0]["per_page"] == "100"
    assert len(sleeps) == 2  # a pause between pages, none before the first
    assert batch.report.requests == 3


def test_past_and_far_future_shows_are_trimmed_and_counted() -> None:
    page = [
        show(1, when="11/12/2026 8:00 pm"),
        show(2, when="03/01/2026 8:00 pm"),
        show(3, when="01/06/2027 8:00 pm"),
    ]
    batch = _source(Handled(_pages([page]))).fetch(_WINDOW, now=_NOW)
    assert [c.uid for c in batch.candidates] == ["lodgeroom:1"]
    assert batch.report.outside_window == 2
    assert batch.report.seen == 3


def test_unusable_shows_are_counted_and_the_rest_come_through() -> None:
    bad = show(9, when="whenever")
    batch = _source(Handled(_pages([[show(1), bad]]))).fetch(_WINDOW, now=_NOW)
    assert len(batch.candidates) == 1
    assert batch.report.skipped == {"bad_date": 1}


def test_a_show_seen_twice_is_kept_once_and_results_are_in_date_order() -> None:
    page = [show(2, when="11/25/2026 8:00 pm"), show(1, when="11/12/2026 8:00 pm"), show(1)]
    batch = _source(Handled(_pages([page]))).fetch(_WINDOW, now=_NOW)
    assert [c.uid for c in batch.candidates] == ["lodgeroom:1", "lodgeroom:2"]


def test_a_feed_that_is_not_a_list_of_shows_is_an_error() -> None:
    handled = Handled(lambda _p: httpx.Response(200, json={"code": "rest_no_route"}))
    with pytest.raises(SourceFetchError, match="not a list of shows"):
        _source(handled).fetch(_WINDOW, now=_NOW)


def test_a_missing_page_count_means_one_page() -> None:
    handled = Handled(lambda _p: httpx.Response(200, json=[show(1)]))
    batch = _source(handled).fetch(_WINDOW, now=_NOW)
    assert len(batch.candidates) == 1
    assert len(handled.queries) == 1


def test_the_configured_venue_zone_is_used() -> None:
    config = LodgeRoomConfig(tz="America/New_York")
    source = LodgeRoomEventSource(JsonClient(http=Handled(_pages([[show(1)]])).client), config)
    assert source.fetch(_WINDOW, now=_NOW).candidates[0].when is not None
