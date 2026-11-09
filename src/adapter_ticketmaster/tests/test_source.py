from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, cast

from tm_fakes import KEY, Clock, Handled, fixture, ok

from last_newsletter_adapter_ticketmaster import (
    TicketmasterClient,
    TicketmasterConfig,
    TicketmasterEventSource,
)
from last_newsletter_adapter_ticketmaster.source import RESULT_CAP
from last_newsletter_core.event_ports import EventSource, SourceWindow

if TYPE_CHECKING:
    import httpx

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_WINDOW = SourceWindow(date_from=date(2026, 11, 20), date_to=date(2026, 11, 26))


def _event(n: int, day: date, title: str = "") -> dict[str, object]:
    return {
        "id": f"e{n}",
        "name": title or f"Show {n}",
        "url": f"https://www.ticketmaster.com/event/e{n}",
        "dates": {
            "start": {"localDate": day.isoformat(), "localTime": "20:00:00"},
            "timezone": "America/Los_Angeles",
            "status": {"code": "onsale"},
        },
        "classifications": [{"segment": {"name": "Music"}, "genre": {"name": "Rock"}}],
        "_embedded": {"venues": [{"name": "The Echo", "city": {"name": "Los Angeles"}}]},
    }


def _page(
    events: list[dict[str, object]], total: int, size: int = 200, number: int = 0
) -> httpx.Response:
    return ok(
        {
            "_embedded": {"events": events},
            "page": {
                "size": size,
                "totalElements": total,
                "totalPages": -(-total // size),
                "number": number,
            },
        }
    )


def _source(handled: Handled, *, dma_id: str = "") -> TicketmasterEventSource:
    clock = Clock()
    client = TicketmasterClient(
        KEY,
        http=handled.client,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        wall_clock=clock.wall_clock,
    )
    config = TicketmasterConfig(city="Los Angeles", region="CA", dma_id=dma_id)
    return TicketmasterEventSource(client, config)


def _day_of(event: dict[str, object]) -> date:
    dates = cast("dict[str, dict[str, str]]", event["dates"])
    return date.fromisoformat(dates["start"]["localDate"])


def test_it_is_an_event_source_named_after_the_service() -> None:
    source: EventSource = _source(Handled(lambda _p: _page([], 0)))
    assert source.name == "ticketmaster"


def test_a_realistic_page_yields_music_events_and_counts_what_it_skipped() -> None:
    page = fixture("events_page.json")
    batch = _source(Handled(lambda _p: ok(page))).fetch(_WINDOW, now=_NOW)
    assert [c.title for c in batch.candidates] == ["Mdou Moctar", "Door Time TBA"]
    assert batch.report.seen == 5
    assert batch.report.skipped == {"cancelled": 1, "not_in_category": 1, "postponed": 1}
    assert batch.report.requests == 1


def test_the_request_asks_for_music_in_the_city_and_carries_the_key_only_as_apikey() -> None:
    handled = Handled(lambda _p: _page([], 0))
    _source(handled, dma_id="324").fetch(_WINDOW, now=_NOW)
    sent = handled.queries[0]
    assert sent["city"] == "Los Angeles"
    assert sent["stateCode"] == "CA"
    assert sent["countryCode"] == "US"
    assert sent["classificationName"] == "music"
    assert sent["dmaId"] == "324"
    assert sent["sort"] == "date,asc"
    assert sent["apikey"] == KEY
    assert [k for k, v in sent.items() if v == KEY and k != "apikey"] == []


def test_the_end_of_the_window_is_widened_a_day_for_evenings_on_the_next_utc_day() -> None:
    handled = Handled(lambda _p: _page([], 0))
    _source(handled).fetch(_WINDOW, now=_NOW)
    assert handled.queries[0]["startDateTime"] == "2026-11-20T00:00:00Z"
    assert handled.queries[0]["endDateTime"] == "2026-11-27T23:59:59Z"


def test_events_just_outside_the_asked_dates_are_trimmed_and_counted() -> None:
    inside, outside = _event(1, date(2026, 11, 26)), _event(2, date(2026, 11, 27))
    batch = _source(Handled(lambda _p: _page([inside, outside], 2))).fetch(_WINDOW, now=_NOW)
    assert [c.title for c in batch.candidates] == ["Show 1"]
    assert batch.report.outside_window == 1


def test_every_page_of_a_search_is_fetched() -> None:
    days = [date(2026, 11, 20) + timedelta(days=i % 5) for i in range(450)]
    events = [_event(i, day) for i, day in enumerate(days)]

    def handler(params: dict[str, str]) -> httpx.Response:
        number, size = int(params["page"]), int(params["size"])
        return _page(events[number * size : (number + 1) * size], len(events), size, number)

    handled = Handled(handler)
    batch = _source(handled).fetch(_WINDOW, now=_NOW)
    assert len(batch.candidates) == 450
    assert [q["page"] for q in handled.queries] == ["0", "1", "2"]
    assert batch.report.truncated == 0


def test_a_search_over_the_cap_is_split_so_nothing_is_lost() -> None:
    every = [_event(i, date(2026, 11, 20) + timedelta(days=i % 7)) for i in range(1500)]

    def handler(params: dict[str, str]) -> httpx.Response:
        start = date.fromisoformat(params["startDateTime"][:10])
        end = date.fromisoformat(params["endDateTime"][:10]) - timedelta(days=1)
        inside = [e for e in every if start <= _day_of(e) <= end]
        number, size = int(params["page"]), int(params["size"])
        return _page(inside[number * size : (number + 1) * size], len(inside), size, number)

    handled = Handled(handler)
    batch = _source(handled).fetch(_WINDOW, now=_NOW)
    assert len(batch.candidates) == 1500
    assert batch.report.truncated == 0
    widths = {
        (
            date.fromisoformat(q["endDateTime"][:10]) - date.fromisoformat(q["startDateTime"][:10])
        ).days
        for q in handled.queries
    }
    assert min(widths) < 7  # the 7-day window was halved


def test_a_single_day_over_the_cap_is_fetched_to_the_cap_and_the_loss_is_reported() -> None:
    day = date(2026, 11, 20)
    one_day = SourceWindow(date_from=day, date_to=day)
    every = [_event(i, day) for i in range(RESULT_CAP + 250)]

    def handler(params: dict[str, str]) -> httpx.Response:
        number, size = int(params["page"]), int(params["size"])
        return _page(every[number * size : (number + 1) * size], len(every), size, number)

    handled = Handled(handler)
    batch = _source(handled).fetch(one_day, now=_NOW)
    assert len(batch.candidates) == RESULT_CAP
    assert batch.report.truncated == 250
    assert max(int(q["page"]) for q in handled.queries) == RESULT_CAP // 200 - 1


def test_a_long_range_is_fetched_in_two_week_windows() -> None:
    long_window = SourceWindow(date_from=date(2026, 11, 1), date_to=date(2026, 11, 30))
    handled = Handled(lambda _p: _page([], 0))
    _source(handled).fetch(long_window, now=_NOW)
    starts = sorted(q["startDateTime"][:10] for q in handled.queries)
    assert starts == ["2026-11-01", "2026-11-15", "2026-11-29"]


def test_an_event_seen_in_two_windows_is_returned_once() -> None:
    shared = _event(1, date(2026, 11, 20))
    long_window = SourceWindow(date_from=date(2026, 11, 20), date_to=date(2026, 12, 20))
    batch = _source(Handled(lambda _p: _page([shared], 1))).fetch(long_window, now=_NOW)
    assert len(batch.candidates) == 1


def test_results_come_back_in_date_order() -> None:
    later, sooner = _event(1, date(2026, 11, 25)), _event(2, date(2026, 11, 21))
    batch = _source(Handled(lambda _p: _page([later, sooner], 2))).fetch(_WINDOW, now=_NOW)
    assert [c.title for c in batch.candidates] == ["Show 2", "Show 1"]


def test_a_page_without_events_is_just_empty() -> None:
    handled = Handled(lambda _p: ok({"page": {"totalElements": 0}}))
    assert _source(handled).fetch(_WINDOW, now=_NOW).candidates == []


def test_the_key_is_never_part_of_what_the_source_reports() -> None:
    page = fixture("events_page.json")
    batch = _source(Handled(lambda _p: ok(page))).fetch(_WINDOW, now=_NOW)
    assert KEY not in repr(batch)


def test_an_event_returned_by_several_windows_is_counted_once_in_the_report() -> None:
    page = fixture("events_page.json")
    long_window = SourceWindow(date_from=date(2026, 11, 1), date_to=date(2026, 12, 20))
    batch = _source(Handled(lambda _p: ok(page))).fetch(long_window, now=_NOW)
    assert len(batch.candidates) == 2
    assert batch.report.seen == 5
    assert batch.report.skipped == {"cancelled": 1, "not_in_category": 1, "postponed": 1}
    assert batch.report.requests == 4
