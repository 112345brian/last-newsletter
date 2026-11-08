from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from event_fakes import InMemoryEventRepository

from last_newsletter_core.events import (
    AllDay,
    EntityRef,
    EntityRole,
    Event,
    EventId,
    EventKind,
    ItemState,
    MatchRule,
    Mention,
    Timed,
)
from last_newsletter_core.use_cases.list_upcoming_events import (
    ListUpcomingEventsUseCase,
    UpcomingEvents,
    upcoming_from_events,
)

LA = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 12, 10, 12, 0, tzinfo=LA)
_SEEN = datetime(2026, 12, 1, tzinfo=UTC)


def _id(n: int) -> EventId:
    return EventId(UUID(int=n))


def _mention(n: int, message: str = "m1", evidence: str = "x") -> Mention:
    return Mention(
        message_id=message,
        seen_at=_SEEN,
        source="s",
        evidence=evidence,
        match_rule=MatchRule.NEW,
        cited_event_id=_id(n),
    )


def timed(start: datetime, end: datetime | None = None) -> Timed:
    return Timed(start=start, tz_name="America/Los_Angeles", end=end)


def make(n: int, when: Timed | AllDay, title: str = "Show", **extra: object) -> Event:
    base = Event(
        id=_id(n),
        kind=EventKind.EVENT,
        title=title,
        summary="",
        when=when,
        mentions=(_mention(n),),
        first_seen=_SEEN,
        last_seen=_SEEN,
    )
    return replace(base, **extra)


def at(day: int, hour: int, minute: int = 0, month: int = 12) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=LA)


def titles(result: UpcomingEvents) -> list[str]:
    return [e.title for d in result.days for e in d.events]


def test_empty_ledger_gives_an_empty_window() -> None:
    result = upcoming_from_events([], now=NOW, tz_name="America/Los_Angeles")
    assert result.days == ()
    assert result.event_count == 0
    assert (result.first_day, result.last_day) == (date(2026, 12, 10), date(2026, 12, 23))


def test_groups_by_date_ordered_by_start_with_all_day_first() -> None:
    events = [
        make(1, timed(at(12, 21)), "Late"),
        make(2, timed(at(12, 19)), "Early"),
        make(3, AllDay(date(2026, 12, 12)), "Market"),
        make(4, timed(at(11, 20)), "Day before"),
    ]
    result = upcoming_from_events(events, now=NOW, tz_name="America/Los_Angeles")
    assert [d.day for d in result.days] == [date(2026, 12, 11), date(2026, 12, 12)]
    assert titles(result) == ["Day before", "Market", "Early", "Late"]


def test_excludes_done_dismissed_expired_and_past_events() -> None:
    events = [
        make(1, timed(at(12, 20)), "Open"),
        make(2, timed(at(12, 20)), "Done", state=ItemState.DONE),
        make(3, timed(at(12, 20)), "Dismissed", state=ItemState.DISMISSED),
        make(4, timed(at(12, 20)), "Expired", state=ItemState.EXPIRED),
        make(5, timed(at(9, 20)), "Past"),
        make(6, timed(at(10, 11)), "Earlier today"),
        make(7, AllDay(date(2026, 12, 9)), "Yesterday all day"),
    ]
    assert titles(upcoming_from_events(events, now=NOW, tz_name="America/Los_Angeles")) == ["Open"]


def test_today_all_day_and_later_today_are_kept() -> None:
    events = [
        make(1, AllDay(date(2026, 12, 10)), "Today all day"),
        make(2, timed(at(10, 20)), "Tonight"),
    ]
    got = titles(upcoming_from_events(events, now=NOW, tz_name="America/Los_Angeles"))
    assert got == ["Today all day", "Tonight"]


def test_snoozed_is_hidden_until_its_time_has_passed() -> None:
    hidden = make(1, timed(at(12, 20)), "Hidden", state=ItemState.SNOOZED, snoozed_until=at(11, 8))
    shown = make(2, timed(at(12, 20)), "Shown", state=ItemState.SNOOZED, snoozed_until=at(9, 8))
    result = upcoming_from_events([hidden, shown], now=NOW, tz_name="America/Los_Angeles")
    assert titles(result) == ["Shown"]


def test_window_default_is_fourteen_dates_and_is_configurable() -> None:
    events = [
        make(1, AllDay(date(2026, 12, 23)), "Last day"),
        make(2, AllDay(date(2026, 12, 24)), "Too far"),
    ]
    assert titles(upcoming_from_events(events, now=NOW, tz_name="America/Los_Angeles")) == [
        "Last day"
    ]
    short = upcoming_from_events(events, now=NOW, days=3, tz_name="America/Los_Angeles")
    assert short.event_count == 0
    assert short.last_day == date(2026, 12, 12)


@pytest.mark.parametrize("days", [0, -1, 400])
def test_rejects_a_silly_window(days: int) -> None:
    with pytest.raises(ValueError, match="days"):
        upcoming_from_events([], now=NOW, days=days)


def test_rejects_naive_now_and_unknown_zone() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        upcoming_from_events([], now=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="time zone"):
        upcoming_from_events([], now=NOW, tz_name="Nowhere/City")


def test_overnight_span_is_one_line_with_its_end_day() -> None:
    event = make(1, timed(at(12, 22), at(13, 2)), "Overnight")
    [day] = upcoming_from_events([event], now=NOW, tz_name="America/Los_Angeles").days
    [line] = day.events
    assert day.day == date(2026, 12, 12)
    assert (line.start, line.end, line.end_day) == (time(22), time(2), date(2026, 12, 13))


def test_late_night_listing_belongs_to_the_previous_night() -> None:
    event = make(1, timed(at(13, 0, 30)), "After midnight", night_of=date(2026, 12, 12))
    [day] = upcoming_from_events([event], now=NOW, tz_name="America/Los_Angeles").days
    assert day.day == date(2026, 12, 12)


def test_a_span_still_running_is_kept_under_the_day_it_began() -> None:
    now = at(10, 1)
    running = make(1, timed(at(9, 22), at(10, 3)), "Still on")
    over = make(2, timed(at(9, 22), at(10, 0, 30)), "Over")
    result = upcoming_from_events([running, over], now=now, tz_name="America/Los_Angeles")
    assert titles(result) == ["Still on"]
    assert result.days[0].day == date(2026, 12, 9)


def test_showtimes_collapse_into_one_line_and_sort() -> None:
    event = make(
        1,
        timed(at(12, 12)),
        "Film",
        showtimes=(time(19), time(12), time(15, 30)),
    )
    [line] = upcoming_from_events([event], now=NOW, tz_name="America/Los_Angeles").days[0].events
    assert line.showtimes == (time(12), time(15, 30), time(19))
    assert line.start == time(12)


def test_event_stays_until_its_last_showtime_has_passed() -> None:
    event = make(1, timed(at(10, 12)), "Film", showtimes=(time(12), time(19)))
    assert titles(upcoming_from_events([event], now=NOW, tz_name="America/Los_Angeles")) == ["Film"]
    late = at(10, 19, 30)
    assert upcoming_from_events([event], now=late, tz_name="America/Los_Angeles").event_count == 0


def test_a_single_showtime_is_not_a_list() -> None:
    event = make(1, timed(at(12, 12)), "Film", showtimes=(time(12),))
    [line] = upcoming_from_events([event], now=NOW, tz_name="America/Los_Angeles").days[0].events
    assert line.showtimes == ()


def test_carries_venue_city_url_id_and_counts_distinct_emails() -> None:
    mentions = (_mention(1, "a"), _mention(1, "b", "y"), _mention(1, "b", "z"))
    event = make(
        1,
        timed(at(12, 20)),
        "Band",
        mentions=mentions,
        entities=(EntityRef("The Hall", EntityRole.VENUE),),
        city="Portland",
        url="https://example.test/e",
    )
    [line] = upcoming_from_events([event], now=NOW, tz_name="America/Los_Angeles").days[0].events
    assert (line.venue, line.city, line.url) == ("The Hall", "Portland", "https://example.test/e")
    assert line.event_id == _id(1)
    assert line.mention_count == 2


def test_more_mentioned_event_ranks_first_at_the_same_time() -> None:
    quiet = make(1, timed(at(12, 20)), "A quiet one")
    loud = make(2, timed(at(12, 20)), "Z loud one", mentions=(_mention(2, "a"), _mention(2, "b")))
    result = upcoming_from_events([quiet, loud], now=NOW, tz_name="America/Los_Angeles")
    assert titles(result) == ["Z loud one", "A quiet one"]


def test_order_does_not_depend_on_input_order() -> None:
    events = [make(i, timed(at(12, 20)), "Same") for i in (3, 1, 2)]
    forward = upcoming_from_events(events, now=NOW, tz_name="America/Los_Angeles")
    backward = upcoming_from_events(events[::-1], now=NOW, tz_name="America/Los_Angeles")
    assert forward == backward


def test_dst_spring_forward_window_is_still_fourteen_dates() -> None:
    # US clocks jump on 2027-03-14; the window is counted in dates, not 24 h blocks.
    now = datetime(2027, 3, 10, 23, 30, tzinfo=LA)
    events = [
        make(1, AllDay(date(2027, 3, 23)), "Last day"),
        make(2, AllDay(date(2027, 3, 24)), "Too far"),
        make(3, timed(at(14, 2, 30, month=3).replace(year=2027)), "In the gap"),
    ]
    result = upcoming_from_events(events, now=now, tz_name="America/Los_Angeles")
    assert result.last_day == date(2027, 3, 23)
    assert titles(result) == ["In the gap", "Last day"]


def test_dst_fall_back_showtimes_use_wall_clock() -> None:
    # 2026-11-01 01:30 happens twice; the later showtime must still be found upcoming.
    now = datetime(2026, 11, 1, 0, 30, tzinfo=LA)
    start = datetime(2026, 11, 1, 1, 30, tzinfo=LA)
    event = make(1, timed(start), "Twice", showtimes=(time(1, 30), time(20)))
    [line] = upcoming_from_events([event], now=now, tz_name="America/Los_Angeles").days[0].events
    assert line.showtimes == (time(1, 30), time(20))


def test_now_in_utc_uses_the_local_date_of_the_zone() -> None:
    # 2026-12-11 03:00 UTC is still the 10th in Los Angeles.
    now = datetime(2026, 12, 11, 3, 0, tzinfo=UTC)
    event = make(1, AllDay(date(2026, 12, 10)), "Still today there")
    result = upcoming_from_events([event], now=now, tz_name="America/Los_Angeles")
    assert titles(result) == ["Still today there"]


def test_very_long_title_is_carried_whole() -> None:
    title = "W" * 5000
    [line] = (
        upcoming_from_events(
            [make(1, timed(at(12, 20)), title)], now=NOW, tz_name="America/Los_Angeles"
        )
        .days[0]
        .events
    )
    assert line.title == title


def test_use_case_reads_only_open_events_from_the_port() -> None:
    repo = InMemoryEventRepository()
    repo.events[_id(1)] = make(1, timed(at(12, 20)), "Open")
    repo.events[_id(2)] = make(2, timed(at(12, 20)), "Done", state=ItemState.DONE)
    before = dict(repo.events)
    result = ListUpcomingEventsUseCase(repo).execute(now=NOW, tz_name="America/Los_Angeles")
    assert titles(result) == ["Open"]
    assert repo.writes == 0
    assert repo.events == before


def test_use_case_lets_a_port_failure_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    def locked() -> list[Event]:
        msg = "database is locked"
        raise OSError(msg)

    repo = InMemoryEventRepository()
    monkeypatch.setattr(repo, "list_open", locked)
    with pytest.raises(OSError, match="locked"):
        ListUpcomingEventsUseCase(repo).execute(now=NOW)


def test_events_are_not_mutated() -> None:
    event = make(1, timed(at(12, 20)), "Open")
    snapshot = replace(event)
    upcoming_from_events([event], now=NOW + timedelta(days=1))
    assert event == snapshot
