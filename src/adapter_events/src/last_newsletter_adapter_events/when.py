"""Parse the model's `start_text` into a `PartialWhen` without ever inventing a year.

The year is only set when four digits that look like a year appear in the text the model
quoted. Everything else (missing year, weekday-only) stays partial for core's rule to resolve.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import re
from datetime import time as clock_time

from last_newsletter_core.events import PartialWhen

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
    times = _times(text)
    end_times = _times(end_text)
    start = times[0] if times else None
    end = times[1] if len(times) > 1 else (end_times[0] if end_times else None)
    late = start is not None and start.hour < _LATE_NIGHT_BEFORE_HOUR and _has_meridiem(text)
    return PartialWhen(
        year=year,
        month=month,
        day=day,
        weekday=_weekday(text),
        time=start,
        end_time=end,
        late_night=late,
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


def _times(text: str) -> list[clock_time]:
    found: list[tuple[int, clock_time]] = []
    for m in _TIME.finditer(text):
        hour, minute, meridiem = int(m[1]), int(m[2] or 0), m[3].lower()
        if 1 <= hour <= _MAX_MONTH and minute <= _MAX_MINUTE:
            pm = 12 if meridiem == "pm" else 0
            found.append((m.start(), clock_time(hour % 12 + pm, minute)))
    if not found:
        found = [(m.start(), clock_time(int(m[1]), int(m[2]))) for m in _TIME24.finditer(text)]
    return [t for _, t in sorted(found)]


def _has_meridiem(text: str) -> bool:
    return _TIME.search(text) is not None
