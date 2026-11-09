from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest
from ical_fakes import calendar_text, served

from last_newsletter_adapter_ical import IcalClient, IcalConfig, IcalEventSource
from last_newsletter_adapter_ical.client import MAX_BYTES
from last_newsletter_core.event_ports import EventSource, SourceFetchError, SourceWindow

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_WINDOW = SourceWindow(date_from=date(2026, 11, 20), date_to=date(2026, 11, 26))
_URL = "https://calendar.example.com/feed.ics?token=SECRET-TOKEN"


def _source(http: httpx.Client, **config: str) -> IcalEventSource:
    cfg = IcalConfig(name="feed", url=_URL, **config)
    return IcalEventSource(IcalClient(http=http), cfg)


def _event(uid: str, day: str, title: str = "Show") -> list[str]:
    return [f"UID:{uid}", f"SUMMARY:{title}", f"DTSTART:{day}T040000Z"]


def test_it_is_an_event_source_named_by_its_configuration() -> None:
    source: EventSource = _source(served(calendar_text()))
    assert source.name == "feed"


def test_a_feed_becomes_candidates_with_a_report_of_what_was_left_out() -> None:
    text = calendar_text(
        _event("a", "20261121", "Band A"),
        _event("b", "20261122", "Band B"),
        [*_event("c", "20261123"), "STATUS:CANCELLED"],
        ["SUMMARY:No uid", "DTSTART:20261121T040000Z"],
        _event("d", "20261201", "Too late"),
    )
    batch = _source(served(text)).fetch(_WINDOW, now=_NOW)
    assert [c.title for c in batch.candidates] == ["Band A", "Band B"]
    assert batch.report.seen == 5
    assert batch.report.skipped == {"cancelled": 1, "no_uid": 1}
    assert batch.report.outside_window == 1
    assert batch.report.requests == 1


def test_results_are_in_date_order_and_a_repeated_uid_is_kept_once() -> None:
    text = calendar_text(
        _event("b", "20261125", "Later"), _event("a", "20261121", "Sooner"), _event("a", "20261121")
    )
    batch = _source(served(text)).fetch(_WINDOW, now=_NOW)
    assert [c.title for c in batch.candidates] == ["Sooner", "Later"]


def test_a_configured_venue_applies_to_every_event() -> None:
    batch = _source(served(calendar_text(_event("a", "20261121"))), venue="The Smell").fetch(
        _WINDOW, now=_NOW
    )
    assert [e.name for e in batch.candidates[0].entities] == ["The Smell"]


def test_an_empty_calendar_is_a_quiet_success() -> None:
    batch = _source(served(calendar_text())).fetch(_WINDOW, now=_NOW)
    assert batch.candidates == []
    assert batch.report.seen == 0


def test_text_that_is_not_a_calendar_is_an_error() -> None:
    with pytest.raises(SourceFetchError, match="not a valid iCalendar"):
        _source(served("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:garbage\r\nEND:VEVENT")).fetch(
            _WINDOW, now=_NOW
        )


def test_a_redirect_is_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old.ics":
            return httpx.Response(301, headers={"location": "https://calendar.example.com/new.ics"})
        return httpx.Response(200, text=calendar_text(_event("a", "20261121")))

    http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    cfg = IcalConfig(name="feed", url="https://calendar.example.com/old.ics")
    batch = IcalEventSource(IcalClient(http=http), cfg).fetch(_WINDOW, now=_NOW)
    assert len(batch.candidates) == 1


@pytest.mark.parametrize("status", [403, 404, 500])
def test_an_error_status_is_reported_without_the_url(status: int) -> None:
    with pytest.raises(SourceFetchError) as caught:
        _source(served("", status)).fetch(_WINDOW, now=_NOW)
    assert str(status) in str(caught.value)
    assert "SECRET-TOKEN" not in str(caught.value)


def test_a_network_error_is_reported_by_type_and_never_leaks_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        message = f"failed for {request.url}"
        raise httpx.ConnectError(message)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(SourceFetchError) as caught:
        _source(http).fetch(_WINDOW, now=_NOW)
    assert "ConnectError" in str(caught.value)
    assert "SECRET-TOKEN" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_a_feed_over_the_size_cap_is_refused() -> None:
    huge = "BEGIN:VCALENDAR\r\n" + "X-FILLER:" + "a" * (MAX_BYTES + 10)
    with pytest.raises(SourceFetchError, match="larger than"):
        _source(served(huge)).fetch(_WINDOW, now=_NOW)


def test_the_token_in_the_feed_url_is_never_part_of_what_the_source_reports() -> None:
    batch = _source(served(calendar_text(_event("a", "20261121")))).fetch(_WINDOW, now=_NOW)
    assert "SECRET-TOKEN" not in repr(batch)
