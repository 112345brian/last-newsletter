"""Parse the model's `start_text` into a `PartialWhen` without ever inventing a year.

The year is only set when four digits that look like a year appear in the text the model
quoted. Everything else (missing year, weekday-only) stays partial for core's rule to resolve.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import re
from datetime import date
from datetime import time as clock_time
from itertools import pairwise

from concert_tracker_core.events import PartialWhen

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
_WEEKDAYS = {d: i for i, d in enumerate(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])}
_MONTH_DAY = re.compile(r"\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.IGNORECASE)
_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3,9})\b", re.IGNORECASE)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s?(am|pm)\b", re.IGNORECASE)
_TIME24 = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_FOUR_DIGITS = 4
_MAX_MONTH = 12
_MAX_DAY = 31
_MAX_MINUTE = 59
_MIN_WORD = 3
_YEAR = re.compile(r"\b(20\d{2})\b")


def parse_when(start_text: str, end_text: str = "", *, tz: str | None = None) -> PartialWhen:
    text = start_text.strip()
    year = month = day = None
    if iso := _ISO.search(text):
        year, month, day = int(iso[1]), int(iso[2]), int(iso[3])
    elif md := _month_day(text):
        month, day = md
    elif sl := _SLASH.search(text):
        month, day = int(sl[1]), int(sl[2])
        if sl[3] and len(sl[3]) == _FOUR_DIGITS:
            year = int(sl[3])
    if year is None and (y := _YEAR.search(text)):
        year = int(y[1])
    if month is not None and not 1 <= month <= _MAX_MONTH:
        month = day = None
    if day is not None and not 1 <= day <= _MAX_DAY:
        month = day = None
    raw = text if not end_text.strip() else f"{text} - {end_text.strip()}"
    times, ranged = _times(text)
    if len(starts := _listed_starts(text)) == _MIN_LISTED_DAYS and is_overnight_span(text, starts):
        times, ranged = times[:2], True  # one span: start on the first day, end on the next
    end_times = _times(end_text)[0]
    start = times[0] if times else None
    end = times[1] if ranged and len(times) > 1 else (end_times[0] if end_times else None)
    showtimes = tuple(times) if not ranged and len(times) > 1 else ()
    late = start is not None and start.hour < _LATE_NIGHT_BEFORE_HOUR and _has_meridiem(text)
    return PartialWhen(
        year=year,
        month=month,
        day=day,
        weekday=_weekday(text),
        time=start,
        end_time=end,
        late_night=late,
        showtimes=showtimes,
        tz=tz,
        raw_text=raw[:200],
    )


def _month_day(text: str) -> tuple[int, int] | None:
    for m in _MONTH_DAY.finditer(text):
        if (month := _MONTHS.get(m[1][:3].lower())) is not None and _is_month_word(m[1]):
            return month, int(m[2])
    for m in _DAY_MONTH.finditer(text):
        if (month := _MONTHS.get(m[2][:3].lower())) is not None and _is_month_word(m[2]):
            return month, int(m[1])
    return None


def _is_month_word(word: str) -> bool:
    w = word.lower()
    return len(w) >= _MIN_WORD and any(name.startswith(w) for name in _MONTH_NAMES)


_MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
)  # fmt: skip


def _weekday(text: str) -> int | None:
    for word in re.findall(r"[A-Za-z]+", text):
        w = word.lower()
        if w[:3] in _WEEKDAYS and (len(w) == _MIN_WORD or w in _FULL_DAYS):
            return _WEEKDAYS[w[:3]]
    return None


_FULL_DAYS = frozenset(
    {"monday", "tuesday", "tues", "wednesday", "thursday", "thurs", "thur"}
    | {"friday", "saturday", "sunday"}
)


_LATE_NIGHT_BEFORE_HOUR = 6


_RANGE_GAP = re.compile(r"^\s*(?:[-\u2013\u2014]|to|until|till)\s*$", re.IGNORECASE)


def _times(text: str) -> tuple[list[clock_time], bool]:
    """The clock times in `text`, in order, and whether the first two form a range ("9pm-2am",
    "9pm to 2am") rather than a list of start times ("12PM, 3:30PM, 7PM")."""
    found: list[tuple[int, int, clock_time]] = []
    for m in _TIME.finditer(text):
        hour, minute, meridiem = int(m[1]), int(m[2] or 0), m[3].lower()
        if 1 <= hour <= _MAX_MONTH and minute <= _MAX_MINUTE:
            pm = 12 if meridiem == "pm" else 0
            found.append((m.start(), m.end(), clock_time(hour % 12 + pm, minute)))
    if not found:
        found = [
            (m.start(), m.end(), clock_time(int(m[1]), int(m[2]))) for m in _TIME24.finditer(text)
        ]
    found.sort()
    ranged = len(found) > 1 and _RANGE_GAP.match(text[found[0][1] : found[1][0]]) is not None
    return [t for _, _, t in found], ranged


_LISTED_DAY = re.compile(
    r"\b(?:mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:rs?|rsday)?|fri(?:day)?"
    r"|sat(?:urday)?|sun(?:day)?)\b\.?,?\s+"
    r"(?:the\s+)?(?:[a-z]{3,9}\.?\s+\d{1,2}|\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?[a-z]{3,9}|\d{1,2}/\d{1,2})",
    re.IGNORECASE,
)


def _listed_starts(text: str) -> list[int]:
    return [
        m.start()
        for m in _LISTED_DAY.finditer(text)
        if _month_day(m.group(0)) is not None or "/" in m.group(0)
    ]


def split_listing(start_text: str) -> list[str]:
    """Cut one listing that names several dated days ("Friday, November 13th - 12PM, 7PM Saturday,
    November 14th - 12PM") into one text per day. Text with fewer than two such days is returned
    whole. Only a weekday followed by a month and day starts a segment."""
    starts = _listed_starts(start_text)
    if len(starts) < _MIN_LISTED_DAYS:
        return [start_text]
    if is_overnight_span(start_text, starts):
        return [start_text]
    bounds = [*starts, len(start_text)]
    return [start_text[a:b].strip() for a, b in pairwise(bounds)]


_MIN_LISTED_DAYS = 2


def is_overnight_span(text: str, starts: list[int]) -> bool:
    """Exactly two consecutive listed days, each with one single time and the second time
    earlier than the first ("Friday, November 6th - 6:30PM Saturday, November 7th - 9AM"): one
    overnight span (an end time on the next day), not two sessions. A later or equal second time,
    a list of showtimes, or non-consecutive days stay one event per date."""
    if len(starts) != _MIN_LISTED_DAYS:
        return False
    first, second = text[: starts[1]], text[starts[1] :]
    (t1, r1), (t2, r2) = _times(first), _times(second)
    one, two = _month_day(first), _month_day(second)
    if len(t1) != 1 or len(t2) != 1 or r1 or r2 or one is None or two is None:
        return False
    (m1, d1), (m2, d2) = one, two
    try:
        gap = date(2024, m2, d2) - date(2024, m1, d1)  # 2024: leap year, so Feb 29 is valid
    except ValueError:
        return False
    return gap.days == 1 and t2[0] < t1[0]


def _has_meridiem(text: str) -> bool:
    return _TIME.search(text) is not None
