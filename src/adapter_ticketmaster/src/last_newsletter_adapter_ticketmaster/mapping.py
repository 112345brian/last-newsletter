"""One Discovery API event -> an `EventCandidate`, or the reason it is skipped.

The API's own id becomes the candidate's `uid` and `message_id`, so the identity ladder's first
rung recognises the same event on every later fetch. The `evidence` string is built from the facts
that matter (title, date, time, venue): unchanged facts give an unchanged string, so a rerun is
counted as unchanged, and a reschedule gives a new one, so it is recorded and the event updated.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import re
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

SOURCE = "ticketmaster"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_SUMMARY_CHARS = 280
_DATE_PARTS = 3
_SKIPPED_STATUSES = {"cancelled": "cancelled", "canceled": "cancelled", "postponed": "postponed"}


def _obj(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    return {}


def _items(value: object) -> list[dict[str, object]]:
    return [_obj(v) for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _text(value: object) -> str:
    return _CONTROL.sub(" ", value).strip() if isinstance(value, str) else ""


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _local_time(start: dict[str, object]) -> clock_time | None:
    if start.get("timeTBA") is True or start.get("noSpecificTime") is True:
        return None
    try:
        return clock_time.fromisoformat(_text(start.get("localTime")))
    except ValueError:
        return None


def _price(raw: dict[str, object]) -> str:
    ranges = _items(raw.get("priceRanges"))
    if not ranges:
        return ""
    low, high = _number(ranges[0].get("min")), _number(ranges[0].get("max"))
    currency = _text(ranges[0].get("currency")) or "USD"
    if low is None:
        return ""
    sign = "$" if currency == "USD" else ""
    suffix = "" if currency == "USD" else f" {currency}"
    if high is None or high == low:
        return f"{sign}{low:g}{suffix}"
    return f"{sign}{low:g}-{sign}{high:g}{suffix}"


def _tags(raw: dict[str, object]) -> frozenset[str]:
    names: list[str] = []
    for classification in _items(raw.get("classifications")):
        for key in ("genre", "subGenre"):
            name = _text(_obj(classification.get(key)).get("name")).lower()
            if name and name != "undefined":
                names.append(name)
    return frozenset(names)


def _performers(embedded: dict[str, object]) -> tuple[EntityRef, ...]:
    names = [_text(a.get("name")) for a in _items(embedded.get("attractions"))]
    return tuple(
        EntityRef(name=name, role=EntityRole.HEADLINER if i == 0 else EntityRole.SUPPORT)
        for i, name in enumerate(n for n in names if n)
    )


def _local_date(start: dict[str, object]) -> tuple[int, int, int] | None:
    if start.get("dateTBD") is True or start.get("dateTBA") is True:
        return None
    parts = _text(start.get("localDate")).split("-")
    if len(parts) != _DATE_PARTS:
        return None
    try:
        year, month, day = (int(p) for p in parts)
    except ValueError:
        return None
    return year, month, day


def _skip_reason(
    raw: dict[str, object], dates: dict[str, object], categories: frozenset[str]
) -> str | None:
    if not _text(raw.get("id")):
        return "no_id"
    if not _text(raw.get("name")):
        return "no_title"
    status = _SKIPPED_STATUSES.get(_text(_obj(dates.get("status")).get("code")).lower())
    if status is not None:
        return status
    if _local_date(_obj(dates.get("start"))) is None:
        return "date_tbd"
    segments = {
        _text(_obj(c.get("segment")).get("name")).lower()
        for c in _items(raw.get("classifications"))
    } - {""}
    if categories and segments and not segments & categories:
        return "not_in_category"
    return None


def candidate_from_event(
    raw: dict[str, object], *, now: datetime, categories: frozenset[str]
) -> EventCandidate | str:
    """The candidate, or a short skip reason: "no_id", "no_title", "cancelled", "postponed",
    "date_tbd" or "not_in_category"."""
    dates = _obj(raw.get("dates"))
    reason = _skip_reason(raw, dates, categories)
    if reason is not None:
        return reason
    event_id, title = _text(raw.get("id")), _text(raw.get("name"))
    start = _obj(dates.get("start"))
    local_date = _text(start.get("localDate"))
    year, month, day = _local_date(start) or (0, 0, 0)

    embedded = _obj(raw.get("_embedded"))
    venue = next(iter(_items(embedded.get("venues"))), {})
    venue_name = _text(venue.get("name"))
    tz = _text(dates.get("timezone")) or _text(venue.get("timezone")) or None
    when_time = _local_time(start)
    entities = _performers(embedded)
    if venue_name:
        entities = (*entities, EntityRef(name=venue_name, role=EntityRole.VENUE))
    evidence = (
        f"{SOURCE} {event_id} | {title} | {local_date} "
        f"{when_time.isoformat() if when_time else 'time tbd'} | {venue_name}"
    )
    return EventCandidate(
        message_id=f"{SOURCE}:{event_id}",
        title=title,
        kind=EventKind.EVENT,
        summary=_text(raw.get("info") or raw.get("pleaseNote"))[:_SUMMARY_CHARS],
        when=PartialWhen(
            year=year, month=month, day=day, time=when_time, tz=tz, raw_text=local_date
        ),
        evidence=evidence,
        entities=entities,
        uid=f"{SOURCE}:{event_id}",
        sequence=int(now.timestamp()),
        url=_text(raw.get("url")) or None,
        city=_text(_obj(venue.get("city")).get("name")),
        tags=_tags(raw),
        price=_price(raw),
    )
