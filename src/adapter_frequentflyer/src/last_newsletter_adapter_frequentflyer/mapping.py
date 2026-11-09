"""One Frequent Flyer event -> an `EventCandidate`, or the reason it is skipped.

The API's own id becomes the candidate's `uid` and `message_id` (`frequentflyer:<id>`), and its
ticket link (often a Ticketmaster or Dice page) becomes the `url`, so the identity ladder can
recognise the same event on every later fetch and, when the link matches, from another source.
`evidence` is built from title, date, time and venue: unchanged facts give an unchanged string, a
reschedule gives a new one. About a third of listings have a date but no time; those stay
date-only rather than being given an invented hour.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import re
from datetime import date
from datetime import time as clock_time
from typing import TYPE_CHECKING

from last_newsletter_core.events import (
    EntityRef,
    EntityRole,
    EventCandidate,
    EventKind,
    PartialWhen,
)

if TYPE_CHECKING:
    from datetime import datetime

SOURCE = "frequentflyer"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_SUMMARY_CHARS = 280


def _text(value: object) -> str:
    return _CONTROL.sub(" ", value).strip() if isinstance(value, str) else ""


def _obj(value: object) -> dict[str, object]:
    return {str(k): v for k, v in value.items()} if isinstance(value, dict) else {}


def _clock(value: object) -> clock_time | None:
    try:
        return clock_time.fromisoformat(_text(value))
    except ValueError:
        return None


def _tags(raw: dict[str, object]) -> frozenset[str]:
    names = [_text(raw.get("vibe")), _text(raw.get("curation"))]
    if raw.get("sold_out") is True:
        names.append("sold out")
    return frozenset(n.lower() for n in names if n)


def candidate_from_event(
    raw: dict[str, object], *, now: datetime, city: str = ""
) -> EventCandidate | str:
    """The candidate, or a short skip reason: "no_id", "no_title" or "bad_date"."""
    event_id, title = _text(raw.get("id")), _text(raw.get("title"))
    if not event_id:
        return "no_id"
    if not title:
        return "no_title"
    local_date = _text(raw.get("date"))
    try:
        day = date.fromisoformat(local_date)
    except ValueError:
        return "bad_date"
    start, end = _clock(raw.get("start_time")), _clock(raw.get("end_time"))
    venue_name = _text(_obj(raw.get("venue")).get("name"))
    entities = (EntityRef(name=venue_name, role=EntityRole.VENUE),) if venue_name else ()
    evidence = (
        f"{SOURCE} {event_id} | {title} | {local_date} "
        f"{start.isoformat(timespec='minutes') if start else 'time tbd'} | {venue_name}"
    )
    return EventCandidate(
        message_id=f"{SOURCE}:{event_id}",
        title=title,
        kind=EventKind.EVENT,
        summary=_text(raw.get("description"))[:_SUMMARY_CHARS],
        when=PartialWhen(
            year=day.year,
            month=day.month,
            day=day.day,
            time=start,
            end_time=end if start else None,
            tz=_text(raw.get("timezone")) or None,
            raw_text=local_date,
        ),
        evidence=evidence,
        entities=entities,
        uid=f"{SOURCE}:{event_id}",
        sequence=int(now.timestamp()),
        url=_text(raw.get("ticket_url")) or _text(raw.get("frequent_flyer_url")) or None,
        city=city,
        tags=_tags(raw),
        price=_text(raw.get("price")),
    )
