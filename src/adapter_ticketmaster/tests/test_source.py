from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import cast

from tm_fakes import KEY, Clock, HandlerTransport, fixture, ok, query_of

from last_newsletter_adapter_ticketmaster import (
    HttpResponse,
    TicketmasterClient,
    TicketmasterConfig,
    TicketmasterEventSource,
)
from last_newsletter_adapter_ticketmaster.source import RESULT_CAP
from last_newsletter_core.event_ports import EventSource, SourceQuery

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_QUERY = SourceQuery(
    city="Los Angeles",
    region="CA",
    date_from=date(2026, 11, 20),
    date_to=date(2026, 11, 26),
)


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
) -> HttpResponse:
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


def _source(transport: HandlerTransport, *, dma_id: str = "") -> TicketmasterEventSource:
    clock = Clock()
    client = TicketmasterClient(
        KEY,
        transport=transport,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        wall_clock=clock.wall_clock,
    )
    return TicketmasterEventSource(client, TicketmasterConfig(dma_id=dma_id))


def test_it_is_an_event_source_named_after_the_service() -> None:
    source: EventSource = _source(HandlerTransport(lambda _p: _page([], 0)))
    assert source.name == "ticketmaster"


def test_a_realistic_page_yields_music_events_and_counts_what_it_skipped() -> None:
    page = fixture("events_page.json")
    transport = HandlerTransport(lambda _p: ok(page))
    source = _source(transport)
    found = source.fetch(_QUERY, now=_NOW)
    assert [c.title for c in found] == ["Mdou Moctar", "Door Time TBA"]
    assert source.stats.seen == 5
    assert source.stats.skipped == {"cancelled": 1, "not_in_category": 1, "postponed": 1}
    assert source.stats.requests == 1


def test_the_request_asks_for_music_in_the_city_and_carries_the_key_only_as_apikey() -> None:
    transport = HandlerTransport(lambda _p: _page([], 0))
    _source(transport, dma_id="324").fetch(_QUERY, now=_NOW)
    sent = transport.queries[0]
    assert sent["city"] == "Los Angeles"
    assert sent["stateCode"] == "CA"
    assert sent["countryCode"] == "US"
    assert sent["classificationName"] == "music"
    assert sent["dmaId"] == "324"
    assert sent["sort"] == "date,asc"
    assert sent["apikey"] == KEY
    assert [k for k, v in sent.items() if v == KEY and k != "apikey"] == []


def test_the_end_of_the_window_is_widened_a_day_for_evenings_that_fall_on_the_next_utc_day() -> (
    None
):
    transport = HandlerTransport(lambda _p: _page([], 0))
    _source(transport).fetch(_QUERY, now=_NOW)
    assert transport.queries[0]["startDateTime"] == "2026-11-20T00:00:00Z"
    assert transport.queries[0]["endDateTime"] == "2026-11-27T23:59:59Z"


def test_events_just_outside_the_asked_dates_are_trimmed_and_counted() -> None:
    inside, outside = _event(1, date(2026, 11, 26)), _event(2, date(2026, 11, 27))
    transport = HandlerTransport(lambda _p: _page([inside, outside], 2))
    source = _source(transport)
    assert [c.title for c in source.fetch(_QUERY, now=_NOW)] == ["Show 1"]
    assert source.stats.outside_window == 1


def test_every_page_of_a_window_is_fetched() -> None:
    days = [date(2026, 11, 20) + timedelta(days=i % 5) for i in range(450)]
    events = [_event(i, day) for i, day in enumerate(days)]

    def handler(params: dict[str, str]) -> HttpResponse:
        number, size = int(params["page"]), int(params["size"])
        return _page(events[number * size : (number + 1) * size], len(events), size, number)

    transport = HandlerTransport(handler)
    source = _source(transport)
    found = source.fetch(_QUERY, now=_NOW)
    assert len(found) == 450
    assert [q["page"] for q in transport.queries] == ["0", "1", "2"]
    assert source.stats.truncated == 0


def test_a_window_over_the_cap_is_split_so_nothing_is_lost() -> None:
    every = [_event(i, date(2026, 11, 20) + timedelta(days=i % 7)) for i in range(1500)]

    def handler(params: dict[str, str]) -> HttpResponse:
        start = date.fromisoformat(params["startDateTime"][:10])
        end = date.fromisoformat(params["endDateTime"][:10]) - timedelta(days=1)
        inside = [e for e in every if start <= _day_of(e) <= end]
        number, size = int(params["page"]), int(params["size"])
        return _page(inside[number * size : (number + 1) * size], len(inside), size, number)

    transport = HandlerTransport(handler)
    source = _source(transport)
    found = source.fetch(_QUERY, now=_NOW)
    assert len(found) == 1500
    assert source.stats.truncated == 0
    widths = {
        (
            date.fromisoformat(q["endDateTime"][:10]) - date.fromisoformat(q["startDateTime"][:10])
        ).days
        for q in transport.queries
    }
    assert min(widths) < 7  # the 7-day window was halved


def test_a_single_day_over_the_cap_is_fetched_to_the_cap_and_the_loss_is_reported() -> None:
    day = date(2026, 11, 20)
    one_day = SourceQuery(city="Los Angeles", date_from=day, date_to=day)
    every = [_event(i, day) for i in range(RESULT_CAP + 250)]

    def handler(params: dict[str, str]) -> HttpResponse:
        number, size = int(params["page"]), int(params["size"])
        return _page(every[number * size : (number + 1) * size], len(every), size, number)

    transport = HandlerTransport(handler)
    source = _source(transport)
    found = source.fetch(one_day, now=_NOW)
    assert len(found) == RESULT_CAP
    assert source.stats.truncated == 250
    assert max(int(q["page"]) for q in transport.queries) == RESULT_CAP // 200 - 1


def test_a_long_range_is_fetched_in_two_week_windows() -> None:
    long_query = SourceQuery(
        city="Los Angeles", date_from=date(2026, 11, 1), date_to=date(2026, 11, 30)
    )
    transport = HandlerTransport(lambda _p: _page([], 0))
    _source(transport).fetch(long_query, now=_NOW)
    starts = sorted(q["startDateTime"][:10] for q in transport.queries)
    assert starts == ["2026-11-01", "2026-11-15", "2026-11-29"]


def test_an_event_seen_in_two_windows_is_returned_once() -> None:
    shared = _event(1, date(2026, 11, 20))
    transport = HandlerTransport(lambda _p: _page([shared], 1))
    long_query = SourceQuery(
        city="Los Angeles", date_from=date(2026, 11, 20), date_to=date(2026, 12, 20)
    )
    assert len(_source(transport).fetch(long_query, now=_NOW)) == 1


def test_results_come_back_in_date_order() -> None:
    later, sooner = _event(1, date(2026, 11, 25)), _event(2, date(2026, 11, 21))
    transport = HandlerTransport(lambda _p: _page([later, sooner], 2))
    assert [c.title for c in _source(transport).fetch(_QUERY, now=_NOW)] == ["Show 2", "Show 1"]


def test_a_page_without_events_is_just_empty() -> None:
    transport = HandlerTransport(lambda _p: ok({"page": {"totalElements": 0}}))
    assert _source(transport).fetch(_QUERY, now=_NOW) == []


def test_the_key_is_never_part_of_what_the_source_reports() -> None:
    page = fixture("events_page.json")
    source = _source(HandlerTransport(lambda _p: ok(page)))
    found = source.fetch(_QUERY, now=_NOW)
    blob = repr(found) + repr(source.stats)
    assert KEY not in blob
    assert query_of(f"https://x/?apikey={KEY}")["apikey"] == KEY  # the helper really parses it


def _day_of(event: dict[str, object]) -> date:
    dates = cast("dict[str, dict[str, str]]", event["dates"])
    return date.fromisoformat(dates["start"]["localDate"])


def test_an_event_returned_by_several_windows_is_counted_once_in_the_stats() -> None:
    page = fixture("events_page.json")
    long_query = SourceQuery(
        city="Los Angeles", date_from=date(2026, 11, 1), date_to=date(2026, 12, 20)
    )
    source = _source(HandlerTransport(lambda _p: ok(page)))
    found = source.fetch(long_query, now=_NOW)
    assert len(found) == 2
    assert source.stats.seen == 5
    assert source.stats.skipped == {"cancelled": 1, "not_in_category": 1, "postponed": 1}
    assert source.stats.requests == 4
