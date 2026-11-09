from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest
from ss_fakes import item, ms, page, served

from last_newsletter_adapter_squarespace import (
    SquarespaceClient,
    SquarespaceConfig,
    SquarespaceEventSource,
)
from last_newsletter_adapter_squarespace.client import MAX_BYTES
from last_newsletter_core.event_ports import EventSource, SourceFetchError, SourceWindow

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_WINDOW = SourceWindow(date_from=date(2026, 11, 10), date_to=date(2026, 11, 20))
_URL = "https://www.venue.example/events"


def _source(http: httpx.Client, **config: str) -> SquarespaceEventSource:
    cfg = SquarespaceConfig(name="smell", url=_URL, **({"venue": "The Smell"} | config))
    return SquarespaceEventSource(SquarespaceClient(http=http), cfg)


def _show(item_id: str, day: int, title: str = "") -> dict[str, object]:
    return item(item_id, title or f"Show {item_id}", start=ms(2026, 11, day), url_id=f"s-{item_id}")


def test_it_is_an_event_source_named_by_its_configuration() -> None:
    source: EventSource = _source(served(page()))
    assert source.name == "smell"


def test_upcoming_events_become_candidates_and_the_past_ones_are_ignored() -> None:
    batch = _source(served(page(_show("a", 12), _show("b", 14), past=30))).fetch(_WINDOW, now=_NOW)
    assert [c.title for c in batch.candidates] == ["Show a", "Show b"]
    assert batch.report.seen == 2
    assert batch.report.requests == 1


def test_events_outside_the_window_are_trimmed_and_counted() -> None:
    batch = _source(served(page(_show("a", 12), _show("b", 28)))).fetch(_WINDOW, now=_NOW)
    assert [c.title for c in batch.candidates] == ["Show a"]
    assert batch.report.outside_window == 1


def test_unusable_items_are_counted_and_the_rest_still_come_through() -> None:
    broken = _show("x", 13)
    broken["title"] = ""
    batch = _source(served(page(_show("a", 12), broken))).fetch(_WINDOW, now=_NOW)
    assert len(batch.candidates) == 1
    assert batch.report.skipped == {"no_title": 1}


def test_results_are_in_date_order_and_a_repeated_item_is_kept_once() -> None:
    batch = _source(served(page(_show("b", 15), _show("a", 12), _show("a", 12)))).fetch(
        _WINDOW, now=_NOW
    )
    assert [c.title for c in batch.candidates] == ["Show a", "Show b"]


def test_an_empty_list_of_upcoming_events_is_a_quiet_success() -> None:
    batch = _source(served(page())).fetch(_WINDOW, now=_NOW)
    assert batch.candidates == []
    assert batch.report.seen == 0


def test_json_is_requested_with_the_format_parameter() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=page())

    http = httpx.Client(transport=httpx.MockTransport(handler))
    _source(http).fetch(_WINDOW, now=_NOW)
    assert dict(seen[0].url.params) == {"format": "json"}
    assert seen[0].url.path == "/events"


def test_a_page_that_is_not_an_events_collection_is_an_error() -> None:
    with pytest.raises(SourceFetchError, match="no list of upcoming events"):
        _source(served({"website": {}, "collection": {}})).fetch(_WINDOW, now=_NOW)


@pytest.mark.parametrize("body", [b"<html>not json</html>", b"[1, 2]"])
def test_a_response_that_is_not_a_json_object_is_an_error(body: bytes) -> None:
    with pytest.raises(SourceFetchError, match="did not return JSON"):
        _source(served(body)).fetch(_WINDOW, now=_NOW)


@pytest.mark.parametrize("status", [403, 404, 500])
def test_an_error_status_is_reported_with_its_code(status: int) -> None:
    with pytest.raises(SourceFetchError, match=str(status)):
        _source(served(b"", status)).fetch(_WINDOW, now=_NOW)


def test_a_network_error_is_reported_by_type_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        message = f"failed for {request.url}"
        raise httpx.ConnectError(message)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(SourceFetchError) as caught:
        _source(http).fetch(_WINDOW, now=_NOW)
    assert "ConnectError" in str(caught.value)
    assert "venue.example" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_a_page_over_the_size_cap_is_refused() -> None:
    with pytest.raises(SourceFetchError, match="larger than"):
        _source(served(b"x" * (MAX_BYTES + 10))).fetch(_WINDOW, now=_NOW)


def test_a_redirect_to_the_canonical_host_is_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "venue.example":
            return httpx.Response(301, headers={"location": "https://www.venue.example/events"})
        return httpx.Response(200, json=page(_show("a", 12)))

    http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    cfg = SquarespaceConfig(name="smell", url="https://venue.example/events", venue="The Smell")
    batch = SquarespaceEventSource(SquarespaceClient(http=http), cfg).fetch(_WINDOW, now=_NOW)
    assert len(batch.candidates) == 1
