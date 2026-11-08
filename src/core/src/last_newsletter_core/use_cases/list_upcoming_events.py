"""Application rule: open events from the ledger -> the "Coming up" window of a digest.

Pure and stateless. `now` is passed in; nothing is saved, so a digest stays a function of the raw
mail plus whatever the ledger holds at the moment it is built. `BuildDigestUseCase` knows nothing
about this: the composition root builds an `UpcomingEvents` and hands it to the renderers.

Rules (docs/design/event-ledger.md section 7):
- Only events that are OPEN, or SNOOZED with a `snoozed_until` that has passed, are listed. DONE,
  DISMISSED and EXPIRED never are.
- The window is `days` calendar dates starting with today in `tz_name` (a date count, not a count
  of hours, so a daylight-saving change cannot shift it). An event belongs to the date it is
  listed under (`night_of` when it runs past midnight), and is dropped once it is over: its end
  time, else its last showtime, else its start, else the end of its all-day date. A span that
  began yesterday and is still running is kept, under the date it began.
- One line per event-date. The ledger already holds one event per date, with the several start
  times of that date as `showtimes`; they are carried as one list, not as separate entries.
- Within a date: all-day first, then by start time, then the most-mentioned first (repeated
  mentions rank higher), then title and id so the order is deterministic.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from last_newsletter_core.events import (
    AllDay,
    Event,
    ItemState,
    local_date,
    require_aware,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from last_newsletter_core.event_ports import EventRepository
    from last_newsletter_core.events import EventId

DEFAULT_WINDOW_DAYS = 14
MAX_WINDOW_DAYS = 366


@dataclass(frozen=True, slots=True)
class UpcomingEvent:
    """One line of the "Coming up" section: one event on one date."""

    event_id: EventId
    title: str
    day: date
    all_day: bool
    start: time | None = None
    end: time | None = None
    end_day: date | None = None  # set only when the end falls on a later date than `day`
    showtimes: tuple[time, ...] = ()
    venue: str = ""
    city: str = ""
    url: str | None = None
    mention_count: int = 1  # distinct emails that mentioned it


@dataclass(frozen=True, slots=True)
class UpcomingDay:
    day: date
    events: tuple[UpcomingEvent, ...]


@dataclass(frozen=True, slots=True)
class UpcomingEvents:
    """The window and what falls in it, grouped by date (only dates that have events)."""

    first_day: date
    last_day: date
    days: tuple[UpcomingDay, ...]

    @property
    def event_count(self) -> int:
        return sum(len(d.events) for d in self.days)


def _zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        msg = f"unknown time zone {tz_name!r}"
        raise ValueError(msg) from exc


def _at(day: date, clock: time, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, clock, tzinfo=zone)


def _is_listable(event: Event, now: datetime) -> bool:
    if event.state is ItemState.OPEN:
        return True
    if event.state is ItemState.SNOOZED:
        return event.snoozed_until is None or event.snoozed_until <= now
    return False


def _entry(event: Event) -> tuple[UpcomingEvent, datetime | None, date]:
    """The line for `event`, the moment it is over (None: when its date ends) and its date."""
    base = UpcomingEvent(
        event_id=event.id,
        title=event.title,
        day=local_date(event.when),
        all_day=False,
        venue=event.venue,
        city=event.city,
        url=event.url,
        mention_count=len({m.message_id for m in event.mentions}),
    )
    when = event.when
    if isinstance(when, AllDay):
        return replace(base, day=when.day, all_day=True), None, when.day
    zone = ZoneInfo(when.tz_name)
    start_local = when.start.astimezone(zone)
    day = event.night_of or local_date(when)
    end_local = when.end.astimezone(zone) if when.end is not None else None
    end_day = end_local.date() if end_local is not None and end_local.date() > day else None
    # Several start times on one date: every one of them is listed, the first is `when`'s own.
    showtimes = tuple(sorted(set(event.showtimes))) if len(event.showtimes) > 1 else ()
    over: datetime | None = end_local
    if over is None:
        last = max(showtimes, default=start_local.time())
        over = _at(start_local.date(), last, zone)
    line = replace(
        base,
        day=day,
        all_day=False,
        start=start_local.time(),
        end=end_local.time() if end_local is not None else None,
        end_day=end_day,
        showtimes=showtimes,
    )
    return line, over, day


def _sort_key(line: UpcomingEvent) -> tuple[bool, time, int, str, str]:
    return (
        not line.all_day,
        line.start or time(0),
        -line.mention_count,
        line.title.casefold(),
        str(line.event_id),
    )


def upcoming_from_events(
    events: Iterable[Event],
    *,
    now: datetime,
    days: int = DEFAULT_WINDOW_DAYS,
    tz_name: str = "UTC",
) -> UpcomingEvents:
    """Pick, filter and group `events` for the window starting today in `tz_name`."""
    require_aware(now, "now")
    if not 1 <= days <= MAX_WINDOW_DAYS:
        msg = f"days must be between 1 and {MAX_WINDOW_DAYS}"
        raise ValueError(msg)
    zone = _zone(tz_name)
    today = now.astimezone(zone).date()
    last_day = today + timedelta(days=days - 1)
    by_day: dict[date, list[UpcomingEvent]] = {}
    for event in events:
        if not _is_listable(event, now):
            continue
        line, over, day = _entry(event)
        if day > last_day:
            continue
        if over is None:
            if day < today:
                continue
        elif over <= now:
            continue
        by_day.setdefault(line.day, []).append(line)
    grouped = tuple(
        UpcomingDay(day=d, events=tuple(sorted(by_day[d], key=_sort_key))) for d in sorted(by_day)
    )
    return UpcomingEvents(first_day=today, last_day=last_day, days=grouped)


class ListUpcomingEventsUseCase:
    """Reads the open events from the repository and builds the "Coming up" window.

    Read-only: it only calls `EventRepository.list_open`. Any failure of the repository
    propagates; the caller decides whether a digest can do without the section.
    """

    def __init__(self, events: EventRepository) -> None:
        self._events = events

    def execute(
        self, *, now: datetime, days: int = DEFAULT_WINDOW_DAYS, tz_name: str = "UTC"
    ) -> UpcomingEvents:
        return upcoming_from_events(self._events.list_open(), now=now, days=days, tz_name=tz_name)
