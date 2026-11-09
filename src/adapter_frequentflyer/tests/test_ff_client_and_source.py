from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, cast

import httpx
import pytest
from ff_fakes import Handled, fixture, ok

from last_newsletter_adapter_frequentflyer import (
    FrequentFlyerClient,
    FrequentFlyerConfig,
    FrequentFlyerEventSource,
)
from last_newsletter_core.event_ports import EventSource, SourceFetchError, SourceWindow

if TYPE_CHECKING:
    from collections.abc import Callable

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_WINDOW = SourceWindow(date_from=date(2026, 11, 20), date_to=date(2026, 11, 26))


def _source(handled: Handled, **config: str) -> FrequentFlyerEventSource:
    client = FrequentFlyerClient(http=handled.client, wall_clock=lambda: 1_800_000_000.0)
    return FrequentFlyerEventSource(client, FrequentFlyerConfig(**config))


def _event(n: int, day: date) -> dict[str, object]:
    return {
        "id": f"e{n}",
        "title": f"Show {n}",
        "date": day.isoformat(),
        "start_time": "20:00",
        "timezone": "America/Los_Angeles",
        "venue": {"name": "The Echo"},
        "ticket_url": f"https://tickets.example.com/e/{n}",
    }


def _body(events: list[dict[str, object]], total: int | None = None) -> httpx.Response:
    return ok(
        {
            "city": "Los Angeles",
            "attribution": "Event data from Frequent Flyer. Please link back.",
            "count": len(events),
            "total_matching": len(events) if total is None else total,
            "events": events,
        }
    )


def _within(every: list[dict[str, object]]) -> Callable[[dict[str, str]], httpx.Response]:
    def handler(params: dict[str, str]) -> httpx.Response:
        start, end = date.fromisoformat(params["from"]), date.fromisoformat(params["to"])
        inside = [e for e in every if start <= date.fromisoformat(cast("str", e["date"])) <= end]
        return _body(inside)

    return handler


def test_it_is_an_event_source_named_after_the_service() -> None:
    source: EventSource = _source(Handled(lambda _p: _body([])))
    assert source.name == "frequentflyer"


def test_a_realistic_response_yields_events_and_counts_what_it_skipped() -> None:
    body = fixture("events.json")
    batch = _source(Handled(lambda _p: ok(body))).fetch(_WINDOW, now=_NOW)
    assert [c.title for c in batch.candidates] == [
        "Synthetic Band Night",
        "Date Only Show",
        "Sold Out Gig",
        "No Venue Yet",
    ]
    assert batch.report.seen == 5
    assert batch.report.skipped == {"bad_date": 1}
    assert batch.report.requests == 1


def test_the_attribution_the_api_asks_for_is_passed_on_in_the_report() -> None:
    body = fixture("events.json")
    batch = _source(Handled(lambda _p: ok(body))).fetch(_WINDOW, now=_NOW)
    assert batch.report.notes == (str(body["attribution"]),)


def test_the_request_carries_the_window_the_limit_and_the_filters() -> None:
    handled = Handled(lambda _p: _body([]))
    _source(handled, neighborhood="echo-park", curation="staff pick").fetch(_WINDOW, now=_NOW)
    assert handled.queries == [
        {
            "from": "2026-11-20",
            "to": "2026-11-26",
            "limit": "100",
            "vibe": "music",
            "neighborhood": "echo-park",
            "curation": "staff pick",
        }
    ]


def test_an_empty_vibe_asks_for_every_kind_of_event() -> None:
    handled = Handled(lambda _p: _body([]))
    _source(handled, vibe="").fetch(_WINDOW, now=_NOW)
    assert "vibe" not in handled.queries[0]


def test_a_long_range_is_fetched_a_week_at_a_time() -> None:
    long_window = SourceWindow(date_from=date(2026, 11, 1), date_to=date(2026, 11, 20))
    handled = Handled(lambda _p: _body([]))
    _source(handled).fetch(long_window, now=_NOW)
    assert sorted(q["from"] for q in handled.queries) == ["2026-11-01", "2026-11-08", "2026-11-15"]


def test_a_short_response_is_split_until_nothing_is_missing() -> None:
    every = [_event(i, date(2026, 11, 20) + timedelta(days=i % 7)) for i in range(40)]

    def handler(params: dict[str, str]) -> httpx.Response:
        full = _within(every)(params)
        events = cast("list[dict[str, object]]", full.json()["events"])
        return _body(events[:10], total=len(events))  # the API returns at most 10 here

    handled = Handled(handler)
    batch = _source(handled).fetch(_WINDOW, now=_NOW)
    assert len(batch.candidates) == 40
    assert batch.report.truncated == 0
    assert len(handled.queries) > 1


def test_a_single_day_that_is_still_short_is_reported_as_truncated() -> None:
    day = SourceWindow(date_from=date(2026, 11, 20), date_to=date(2026, 11, 20))
    events = [_event(i, date(2026, 11, 20)) for i in range(5)]
    batch = _source(Handled(lambda _p: _body(events, total=8))).fetch(day, now=_NOW)
    assert len(batch.candidates) == 5
    assert batch.report.truncated == 3


def test_events_outside_the_asked_dates_are_trimmed_and_counted() -> None:
    inside, outside = _event(1, date(2026, 11, 26)), _event(2, date(2026, 11, 27))
    batch = _source(Handled(lambda _p: _body([inside, outside]))).fetch(_WINDOW, now=_NOW)
    assert [c.title for c in batch.candidates] == ["Show 1"]
    assert batch.report.outside_window == 1


def test_an_event_returned_by_two_searches_is_counted_once() -> None:
    shared = _event(1, date(2026, 11, 20))
    long_window = SourceWindow(date_from=date(2026, 11, 20), date_to=date(2026, 12, 10))
    batch = _source(Handled(lambda _p: _body([shared]))).fetch(long_window, now=_NOW)
    assert len(batch.candidates) == 1
    assert batch.report.seen == 1


def test_results_come_back_in_date_order() -> None:
    later, sooner = _event(1, date(2026, 11, 25)), _event(2, date(2026, 11, 21))
    batch = _source(Handled(lambda _p: _body([later, sooner]))).fetch(_WINDOW, now=_NOW)
    assert [c.title for c in batch.candidates] == ["Show 2", "Show 1"]


def _client(response: httpx.Response | Exception) -> FrequentFlyerClient:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        if isinstance(response, Exception):
            raise response
        return response

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return FrequentFlyerClient(http=http, wall_clock=lambda: 1_800_000_000.0)


def test_a_rate_limit_is_reported_with_when_it_resets() -> None:
    limited = httpx.Response(429, headers={"x-ratelimit-reset": "1800000042"})
    with pytest.raises(SourceFetchError, match=r"rate limit.*42 second"):
        _client(limited).get_events({})


def test_a_server_error_is_reported_with_its_status() -> None:
    with pytest.raises(SourceFetchError, match="HTTP 503"):
        _client(httpx.Response(503)).get_events({})


def test_a_redirect_is_not_followed_and_is_an_error() -> None:
    redirect = httpx.Response(302, headers={"location": "https://elsewhere.example/"})
    with pytest.raises(SourceFetchError, match="HTTP 302"):
        _client(redirect).get_events({})


@pytest.mark.parametrize("content", [b"<html>down</html>", b"[1, 2]"])
def test_a_response_that_is_not_a_json_object_is_an_error(content: bytes) -> None:
    with pytest.raises(SourceFetchError, match="not JSON"):
        _client(httpx.Response(200, content=content)).get_events({})


def test_a_network_error_is_reported_by_type_without_the_url() -> None:
    boom = httpx.ConnectError("failed for https://frequentflyerla.com/api/v1/events?x=1")
    with pytest.raises(SourceFetchError) as caught:
        _client(boom).get_events({})
    assert "ConnectError" in str(caught.value)
    assert "frequentflyerla" not in str(caught.value)
    assert caught.value.__cause__ is None
