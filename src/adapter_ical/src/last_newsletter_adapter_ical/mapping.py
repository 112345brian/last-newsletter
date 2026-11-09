"""One VEVENT -> an `EventCandidate`, or the reason it is skipped.

The feed's own `UID` is the event's identity (core's first identity rung is exactly an iCalendar
UID, with `#` and the RECURRENCE-ID appended for one instance of a series), so a calendar that two
sources both re-publish is recognised as the same event without any fuzzy matching. `evidence` is
built from the title, the local date and time, and the raw location: unchanged facts give an
unchanged string, a reschedule or a move gives a new one.

What is deliberately not handled, and counted instead of guessed: recurring rules (`recurring`),
and all-day spans of more than one day (`multi_day`: core models one event per date, and a span
such as a three-month series is not one show).
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import re
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

from last_newsletter_core.events import (
    EntityRef,
    EntityRole,
    EventCandidate,
    EventKind,
    PartialWhen,
)

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from icalendar import Component

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_STATE_ZIP = re.compile(r"[A-Z]{2}(\s+\d{5}(-\d{4})?)?")
_LINK = re.compile(r"\[[^\]]*\]")
_LABEL = re.compile(r"^location\s+", re.IGNORECASE)
_SUMMARY_CHARS = 280
_ONE_DAY = timedelta(days=1)
_CITY_STATE_PARTS = 2


def _text(value: object) -> str:
    return _CONTROL.sub(" ", str(value)).strip() if value is not None else ""


def venue_from_location(location: str) -> str:
    """A venue name from a LOCATION, or "" when it only looks like an address or a city.

    "The Mayan, 1038 S Hill St, Los Angeles" -> "The Mayan"; "Globe Theatre" -> "Globe Theatre";
    "Pomona, CA" and "1038 S Hill St, Los Angeles" -> "". A guess, so a feed's owner can override
    it with `IcalConfig.venue`.
    """
    cleaned = _LABEL.sub("", _LINK.sub("", location).strip())  # some feeds add "Location X [/url]"
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    if not parts:
        return ""
    if len(parts) == _CITY_STATE_PARTS and _STATE_ZIP.fullmatch(parts[1]):
        return ""
    return "" if parts[0][0].isdigit() else parts[0]


def _local(moment: date, tz: ZoneInfo) -> tuple[date, time | None]:
    if isinstance(moment, datetime):
        aware = moment.astimezone(tz) if moment.tzinfo else moment.replace(tzinfo=tz)
        return aware.date(), aware.time().replace(second=0, microsecond=0, tzinfo=None)
    return moment, None


def _end_time(start: date, end: object, tz: ZoneInfo) -> time | None:
    if not (isinstance(start, datetime) and isinstance(end, datetime)):
        return None
    begin = start.astimezone(tz) if start.tzinfo else start.replace(tzinfo=tz)
    finish = end.astimezone(tz) if end.tzinfo else end.replace(tzinfo=tz)
    if finish <= begin or finish - begin >= _ONE_DAY:
        return None
    return finish.time().replace(second=0, microsecond=0, tzinfo=None)


def _categories(event: Component) -> frozenset[str]:
    raw = event.get("CATEGORIES")
    groups = raw if isinstance(raw, list) else [raw]
    names = [_text(c) for group in groups for c in getattr(group, "cats", [])]
    return frozenset(n.lower() for n in names if n)


def _skip_reason(event: Component) -> str | None:
    if not _text(event.get("UID")):
        return "no_uid"
    if not _text(event.get("SUMMARY")):
        return "no_title"
    if _text(event.get("STATUS")).upper() == "CANCELLED":
        return "cancelled"
    if event.get("RRULE") is not None:
        return "recurring"
    if "DTSTART" not in event:
        return "no_date"
    return None


def candidate_from_vevent(
    event: Component, *, name: str, tz: ZoneInfo, now: datetime, venue: str = ""
) -> EventCandidate | str:
    """The candidate, or a short skip reason: "no_uid", "no_title", "cancelled", "recurring",
    "no_date" or "multi_day"."""
    reason = _skip_reason(event)
    if reason is not None:
        return reason
    start = event.decoded("DTSTART")
    end = event.decoded("DTEND") if "DTEND" in event else None
    if not isinstance(start, datetime) and isinstance(end, date) and end - start > _ONE_DAY:
        return "multi_day"
    day, when_time = _local(start, tz)
    uid = _text(event.get("UID"))
    recurrence = event.get("RECURRENCE-ID")
    if recurrence is not None:
        uid = f"{uid}#{event.decoded('RECURRENCE-ID').isoformat()}"
    title, location = _text(event.get("SUMMARY")), _text(event.get("LOCATION"))
    venue_name = venue or venue_from_location(location)
    entities = (EntityRef(name=venue_name, role=EntityRole.VENUE),) if venue_name else ()
    sequence = event.get("SEQUENCE")
    description = _SPACE.sub(" ", _TAGS.sub(" ", _text(event.get("DESCRIPTION")))).strip()
    return EventCandidate(
        message_id=f"{name}:{uid}",
        title=title,
        kind=EventKind.EVENT,
        summary=description[:_SUMMARY_CHARS],
        when=PartialWhen(
            year=day.year,
            month=day.month,
            day=day.day,
            time=when_time,
            end_time=_end_time(start, end, tz),
            tz=tz.key,
            raw_text=day.isoformat(),
        ),
        evidence=(
            f"{name} {uid} | {title} | {day.isoformat()} "
            f"{when_time.isoformat(timespec='minutes') if when_time else 'time tbd'} | {location}"
        ),
        entities=entities,
        uid=uid,
        sequence=int(str(sequence)) if sequence is not None else int(now.timestamp()),
        url=_text(event.get("URL")) or None,
        tags=_categories(event),
    )
