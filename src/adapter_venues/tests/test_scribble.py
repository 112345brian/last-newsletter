from __future__ import annotations

from datetime import UTC, date, datetime
from datetime import time as clock
from zoneinfo import ZoneInfo

import httpx
import pytest
from venue_fakes import Handled

from last_newsletter_adapter_venues import JsonClient, ScribbleConfig, ScribbleEventSource
from last_newsletter_adapter_venues.scribble import candidate_from_event
from last_newsletter_core.event_ports import EventSource, SourceFetchError, SourceWindow
from last_newsletter_core.event_rules import validate_candidate
from last_newsletter_core.events import EntityRole, EventCandidate, EventDraft

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_LA = ZoneInfo("America/Los_Angeles")
_CONFIG = ScribbleConfig()
_WINDOW = SourceWindow(date_from=date(2026, 11, 10), date_to=date(2026, 12, 31))


def _event(
    event_id: str = "e1", title: str = "The Scratch Pad", when: str = "2026-11-11T03:30:00.000Z"
) -> dict[str, object]:
    return {
        "_id": event_id,
        "title": title,
        "date": when,
        "slug": "the-scratch-pad-11-10-26",
        "_updatedAt": "2026-11-05T18:50:39Z",
        "description": "Comedy, with a guest.",
    }


def _map(raw: dict[str, object]) -> EventCandidate:
    outcome = candidate_from_event(raw, _CONFIG, _LA, _NOW)
    assert isinstance(outcome, EventCandidate), outcome
    return outcome


def test_a_utc_instant_is_shown_in_the_venues_zone_and_can_change_the_date() -> None:
    c = _map(_event())  # 03:30Z on the 11th is 7:30pm on the 10th in Los Angeles
    assert c.when is not None
    assert (c.when.year, c.when.month, c.when.day) == (2026, 11, 10)
    assert (c.when.time, c.when.tz) == (clock(19, 30), "America/Los_Angeles")


def test_identity_venue_and_update_order_come_from_the_record() -> None:
    c = _map(_event("abc"))
    assert c.uid == c.message_id == "scribble:abc"
    assert [(e.name, e.role) for e in c.entities] == [("Scribble", EntityRole.VENUE)]
    assert c.sequence == int(datetime(2026, 11, 5, 18, 50, 39, tzinfo=UTC).timestamp())
    assert c.summary == "Comedy, with a guest."
    assert c.url is None  # the public page address is not in the data


@pytest.mark.parametrize(
    ("change", "reason"),
    [({"_id": ""}, "no_id"), ({"title": " "}, "no_title"), ({"date": "soon"}, "bad_date")],
)
def test_records_that_cannot_be_used_are_skipped_with_a_reason(
    change: dict[str, object], reason: str
) -> None:
    assert candidate_from_event(_event() | change, _CONFIG, _LA, _NOW) == reason


def test_evidence_changes_with_a_reschedule_and_not_without_one() -> None:
    assert _map(_event()).evidence == _map(_event()).evidence
    assert _map(_event(when="2026-11-12T03:30:00.000Z")).evidence != _map(_event()).evidence


def test_a_mapped_candidate_passes_core_validation_unchanged() -> None:
    draft = validate_candidate(
        _map(_event()),
        message_body="",
        now=_NOW,
        home_tz="America/Los_Angeles",
        check_evidence=False,
    )
    assert isinstance(draft, EventDraft)
    assert draft.venue == "Scribble"


def _source(handled: Handled) -> ScribbleEventSource:
    return ScribbleEventSource(JsonClient(http=handled.client))


def _results(records: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(200, json={"query": "q", "result": records, "ms": 3})


def test_it_is_an_event_source_named_after_the_venue() -> None:
    source: EventSource = _source(Handled(lambda _p: _results([])))
    assert source.name == "scribble"


def test_the_query_asks_for_upcoming_events_in_order_from_the_public_content_api() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _results([])

    http = httpx.Client(transport=httpx.MockTransport(handler))
    ScribbleEventSource(JsonClient(http=http)).fetch(_WINDOW, now=_NOW)
    assert seen[0].url.host == "59zw0zbs.apicdn.sanity.io"
    assert seen[0].url.path == "/v2024-07-01/data/query/production"
    query = seen[0].url.params["query"]
    assert "scribbleEvent" in query
    assert "dateTime(date) >= dateTime(now())" in query
    assert "order(date asc)" in query
    assert query.endswith("[0...100]")


def test_records_become_candidates_and_the_window_trims_them() -> None:
    records = [_event("a", when="2026-11-13T03:00:00Z"), _event("b", when="2027-03-01T03:00:00Z")]
    batch = _source(Handled(lambda _p: _results(records))).fetch(_WINDOW, now=_NOW)
    assert [c.uid for c in batch.candidates] == ["scribble:a"]
    assert batch.report.outside_window == 1
    assert batch.report.requests == 1


def test_a_full_page_means_ask_for_the_next_one() -> None:
    first = [_event(f"a{i}", when="2026-11-13T03:00:00Z") for i in range(100)]
    second = [_event("b0", when="2026-11-14T03:00:00Z")]

    def handler(params: dict[str, str]) -> httpx.Response:
        return _results(first if params["query"].endswith("[0...100]") else second)

    handled = Handled(handler)
    batch = _source(handled).fetch(_WINDOW, now=_NOW)
    assert len(batch.candidates) == 101
    assert [q["query"].rsplit("[", 1)[1] for q in handled.queries] == ["0...100]", "100...200]"]


def test_a_reply_without_a_result_list_is_an_error() -> None:
    handled = Handled(lambda _p: httpx.Response(200, json={"error": {"description": "bad query"}}))
    with pytest.raises(SourceFetchError, match="no result list"):
        _source(handled).fetch(_WINDOW, now=_NOW)
