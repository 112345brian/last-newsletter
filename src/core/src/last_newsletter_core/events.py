"""Event-ledger entities (docs/design/event-ledger.md section 3): frozen data, no I/O.

Every datetime is timezone-aware; constructors reject naive ones. Text is checked for control
characters (NUL and friends) because the data arrives from untrusted mail.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, NewType
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from datetime import date, datetime
    from datetime import time as clock_time

EventId = NewType("EventId", UUID)
"""Opaque surrogate key. Core never generates one: it comes from the `IdGenerator` port."""

RawRef = NewType("RawRef", str)
"""Opaque handle to a stored raw message, issued by the `RawMessageStore` port."""

_ALLOWED_CONTROL = frozenset("\t\n\r")


def has_control_characters(text: str) -> bool:
    """True when `text` holds NUL or any other control character except tab and newlines."""
    return any(unicodedata.category(c) == "Cc" and c not in _ALLOWED_CONTROL for c in text)


def require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = f"{name} must be timezone-aware"
        raise ValueError(msg)


class EventKind(StrEnum):
    EVENT = "event"
    DEADLINE = "deadline"
    TASK = "task"


class ItemState(StrEnum):
    OPEN = "open"
    DONE = "done"
    DISMISSED = "dismissed"
    SNOOZED = "snoozed"
    EXPIRED = "expired"


class EntityRole(StrEnum):
    HEADLINER = "headliner"
    SUPPORT = "support"
    VENUE = "venue"
    ORGANIZER = "organizer"


class Origin(StrEnum):
    OWNER = "owner"
    EXTRACTOR = "extractor"


class MatchRule(StrEnum):
    """Which rung of the identity ladder linked a mention to its event (audit trail)."""

    NEW = "new"
    UID = "uid"
    URL = "url"
    TITLE_DATE_VENUE = "title_date_venue"
    SIMILAR = "similar"


@dataclass(frozen=True, slots=True)
class EntityRef:
    name: str
    role: EntityRole
    origin: Origin = Origin.EXTRACTOR


@dataclass(frozen=True, slots=True)
class AllDay:
    day: date


@dataclass(frozen=True, slots=True)
class Timed:
    start: datetime
    tz_name: str
    end: datetime | None = None

    def __post_init__(self) -> None:
        require_aware(self.start, "start")
        try:
            ZoneInfo(self.tz_name)
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            msg = f"unknown time zone {self.tz_name!r}"
            raise ValueError(msg) from exc
        if self.end is not None:
            require_aware(self.end, "end")
            if self.end < self.start:
                msg = "end must not be before start"
                raise ValueError(msg)


ItemTime = AllDay | Timed


def local_date(when: ItemTime) -> date:
    """The calendar date an item falls on in its own time zone."""
    if isinstance(when, AllDay):
        return when.day
    return when.start.astimezone(ZoneInfo(when.tz_name)).date()


@dataclass(frozen=True, slots=True)
class Mention:
    """Provenance: one email that cited one event. Never overwritten, only appended."""

    message_id: str
    seen_at: datetime
    source: str
    evidence: str
    match_rule: MatchRule
    cited_event_id: EventId
    raw_date_text: str = ""
    raw_ref: RawRef | None = None

    def __post_init__(self) -> None:
        require_aware(self.seen_at, "seen_at")


@dataclass(frozen=True, slots=True)
class PartialWhen:
    """A date as an extractor found it: possibly no year, possibly a weekday, maybe a time."""

    year: int | None = None
    month: int | None = None
    day: int | None = None
    weekday: int | None = None  # Monday == 0, as date.weekday()
    time: clock_time | None = None
    end_time: clock_time | None = None  # end before/at `time` means it ends the next day
    late_night: bool = False  # listed after midnight but belongs to the previous night
    showtimes: tuple[clock_time, ...] = ()  # every start time listed for this one date
    tz: str | None = None
    raw_text: str = ""


@dataclass(frozen=True, slots=True)
class EventCandidate:
    """Untrusted extractor output. Every field may be missing or wrong.

    `message_id` says which input message it came from. `evidence` is the quoted line it was
    read from. `uid` is the iCalendar UID (append `#` and the RECURRENCE-ID for one instance of
    a series); `sequence` is the iCalendar SEQUENCE.
    """

    message_id: str
    title: str | None = None
    kind: EventKind | None = None
    summary: str = ""
    when: PartialWhen | None = None
    evidence: str = ""
    entities: tuple[EntityRef, ...] = ()
    uid: str | None = None
    sequence: int = 0
    url: str | None = None
    is_recap: bool = False
    city: str = ""
    tags: frozenset[str] = frozenset()
    price: str = ""  # free text, e.g. "$20 | 21+"
    age: str = ""  # free text, e.g. "21+"


@dataclass(frozen=True, slots=True)
class EventDraft:
    """A validated candidate: everything an `Event` has except identity, state and history."""

    kind: EventKind
    title: str
    summary: str
    when: ItemTime
    evidence: str
    raw_date_text: str = ""
    entities: tuple[EntityRef, ...] = ()
    uid: str | None = None
    sequence: int = 0
    url: str | None = None
    city: str = ""
    tags: frozenset[str] = frozenset()
    price: str = ""
    age: str = ""
    night_of: date | None = None
    showtimes: tuple[clock_time, ...] = ()

    @property
    def venue(self) -> str:
        return next((e.name for e in self.entities if e.role is EntityRole.VENUE), "")


@dataclass(frozen=True, slots=True)
class Event:
    """One real-world happening. `when` is the listed start; for a listing that runs past
    midnight, `night_of` is the date of the night it belongs to (the previous day).

    A later email about the same thing adds a `Mention`, not a row.

    One event is one real-world happening on one date. A listing that runs over several days
    (or a film that plays Fri, Sat and Sun) is one event per date, each with its own UUID; the
    several start times within a date are `showtimes` (empty unless there are at least two;
    the first is `when`'s own time).

    `possible_duplicates` is the structured citation column for ambiguous matches: ids of other
    events this might be the same as. Showing a duplicate is safe; hiding a live item is not.
    """

    id: EventId
    kind: EventKind
    title: str
    summary: str
    when: ItemTime
    mentions: tuple[Mention, ...]
    first_seen: datetime
    last_seen: datetime
    entities: tuple[EntityRef, ...] = ()
    state: ItemState = ItemState.OPEN
    snoozed_until: datetime | None = None
    possible_duplicates: tuple[EventId, ...] = field(default_factory=tuple)
    uid: str | None = None
    sequence: int = 0
    url: str | None = None
    city: str = ""
    tags: frozenset[str] = frozenset()
    price: str = ""
    age: str = ""
    night_of: date | None = None
    showtimes: tuple[clock_time, ...] = ()

    def __post_init__(self) -> None:
        if not self.title.strip():
            msg = "title must not be blank"
            raise ValueError(msg)
        free_text = [self.title, self.summary, self.city, self.price, self.age, *self.tags]
        if any(has_control_characters(t) for t in free_text):
            msg = "event text must not contain control characters"
            raise ValueError(msg)
        require_aware(self.first_seen, "first_seen")
        require_aware(self.last_seen, "last_seen")
        if self.snoozed_until is not None:
            require_aware(self.snoozed_until, "snoozed_until")
        if self.last_seen < self.first_seen:
            msg = "last_seen must not be before first_seen"
            raise ValueError(msg)
        if not self.mentions:
            msg = "an event needs at least one mention"
            raise ValueError(msg)
        if self.id in self.possible_duplicates:
            msg = "an event cannot be a possible duplicate of itself"
            raise ValueError(msg)

    @property
    def venue(self) -> str:
        return next((e.name for e in self.entities if e.role is EntityRole.VENUE), "")
