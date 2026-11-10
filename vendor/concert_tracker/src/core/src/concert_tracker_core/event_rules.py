"""Pure rules for the event ledger (docs/design/event-ledger.md section 4): year resolution,
past-date rejection, text and URL normalization, and validation of untrusted candidates.

No clock: `now` is always an argument.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

import re
import unicodedata
from datetime import date, datetime, timedelta
from datetime import time as clock_time
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from concert_tracker_core.events import (
    AllDay,
    EntityRef,
    EventCandidate,
    EventDraft,
    EventKind,
    ItemTime,
    PartialWhen,
    Timed,
    has_control_characters,
    local_date,
    require_aware,
)

PAST_GRACE = timedelta(days=1)
MAX_TITLE_LENGTH = 300
_MAX_URL_LENGTH = 2048
_WEEKDAYS = range(7)
_TRACKING_PARAMS = frozenset(
    {"fbclid", "gclid", "msclkid", "igshid", "mc_cid", "mc_eid", "mkt_tok", "_hsenc", "_hsmi"}
)
_URL = re.compile(r"^(https?)://([^/?#\s]+)([^?#\s]*)(?:\?([^#\s]*))?(?:#\S*)?$", re.IGNORECASE)
_DEFAULT_PORTS = {"http": "80", "https": "443"}


class RejectReason(StrEnum):
    """Why a candidate (or a whole message) was not turned into an event. Always counted."""

    BLANK_TITLE = "blank_title"
    TITLE_TOO_LONG = "title_too_long"
    CONTROL_CHARACTERS = "control_characters"
    MISSING_DATE = "missing_date"
    INVALID_DATE = "invalid_date"
    AMBIGUOUS_YEAR = "ambiguous_year"
    UNKNOWN_TIMEZONE = "unknown_timezone"
    PAST_DATE = "past_date"
    NO_EVIDENCE = "no_evidence"
    EVIDENCE_NOT_IN_MESSAGE = "evidence_not_in_message"
    UNKNOWN_MESSAGE = "unknown_message"
    NAIVE_RECEIVED_AT = "naive_received_at"


def normalize_text(text: str) -> str:
    """Case, accent, width and punctuation-insensitive form used to compare titles and venues."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    decomposed = unicodedata.normalize("NFKD", folded)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[\W_]+", " ", stripped).split())


def canonical_url(url: str) -> str | None:
    """A comparable form of an http(s) URL, or None when it is not one.

    Lowercases the host, drops default ports, fragments, userinfo, tracking parameters and a
    trailing slash, and sorts the remaining query. Hand-parsed because core may not import
    `urllib`.
    """
    text = url.strip()
    match = _URL.match(text) if len(text) <= _MAX_URL_LENGTH else None
    if match is None:
        return None
    scheme = match.group(1).lower()
    host = match.group(2).rpartition("@")[2].lower()
    name, _, port = host.partition(":")
    if not name:
        return None
    if port in {"", _DEFAULT_PORTS[scheme]}:
        host = name
    path = match.group(3).rstrip("/")
    pairs = [
        pair
        for pair in (match.group(4) or "").split("&")
        if pair
        and not pair.lower().startswith("utm_")
        and pair.split("=", 1)[0].lower() not in _TRACKING_PARAMS
    ]
    query = "&".join(sorted(pairs))
    return f"{scheme}://{host}{path}" + (f"?{query}" if query else "")


def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def _year_options(partial: PartialWhen, *, today: date, cutoff: date | None) -> list[date]:
    options: list[date] = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidate = date(year, partial.month or 0, partial.day or 0)
        except ValueError:
            continue
        if partial.weekday is not None and candidate.weekday() != partial.weekday:
            continue
        if cutoff is None or candidate >= cutoff:
            options.append(candidate)
    return options


def _explicit_day(year: int, month: int, day: int) -> date | RejectReason:
    try:
        return date(year, month, day)
    except ValueError:
        return RejectReason.INVALID_DATE


def _resolve_day(partial: PartialWhen, *, today: date, cutoff: date | None) -> date | RejectReason:
    """Pick the calendar date. With no year, choose the one in which month, day and (if given)
    weekday agree, nearest on or after `cutoff` (or nearest to `today` when `cutoff` is None)."""
    if partial.month is None or partial.day is None:
        return RejectReason.MISSING_DATE
    if partial.weekday is not None and partial.weekday not in _WEEKDAYS:
        return RejectReason.INVALID_DATE
    if partial.year is not None:
        return _explicit_day(partial.year, partial.month, partial.day)
    return _pick_year(partial, today=today, cutoff=cutoff)


def _pick_year(partial: PartialWhen, *, today: date, cutoff: date | None) -> date | RejectReason:
    options = _year_options(partial, today=today, cutoff=cutoff)
    if options:
        if cutoff is None:
            return min(options, key=lambda d: abs((d - today).days))
        return min(options)
    if cutoff is not None and _year_options(partial, today=today, cutoff=None):
        return RejectReason.PAST_DATE  # the weekday did pin a year; that day is already behind us
    # No year fits: a weekday that never lines up is ambiguous, an impossible date is invalid.
    return RejectReason.AMBIGUOUS_YEAR if partial.weekday is not None else RejectReason.INVALID_DATE


def resolve_when(
    partial: PartialWhen,
    *,
    now: datetime,
    home_tz: str,
    allow_past: bool = False,
) -> ItemTime | RejectReason:
    """Turn an extractor's partial date into an `ItemTime`, or say why it cannot be one.

    A missing year is chosen so that month, day and weekday agree. Dates more than `PAST_GRACE`
    in the past are rejected unless `allow_past` (the text marks a recap).
    """
    require_aware(now, "now")
    zone = _zone(partial.tz or home_tz)
    if zone is None:
        return RejectReason.UNKNOWN_TIMEZONE
    today = now.astimezone(zone).date()
    cutoff = None if allow_past else today - PAST_GRACE
    chosen = _resolve_day(partial, today=today, cutoff=cutoff)
    if isinstance(chosen, RejectReason):
        return chosen
    if partial.time is None:
        when: ItemTime = AllDay(chosen)
        before_cutoff = cutoff is not None and chosen < cutoff
    else:
        start = datetime.combine(chosen, partial.time.replace(tzinfo=None), tzinfo=zone)
        end = None
        if partial.end_time is not None:
            end = datetime.combine(chosen, partial.end_time.replace(tzinfo=None), tzinfo=zone)
            if end <= start:  # "1:30am-5am" style ranges can also be "10pm-2am"
                end = datetime.combine(
                    chosen + timedelta(days=1), partial.end_time.replace(tzinfo=None), tzinfo=zone
                )
        when = Timed(start=start, tz_name=zone.key, end=end)
        before_cutoff = not allow_past and start < now - PAST_GRACE
    return RejectReason.PAST_DATE if before_cutoff else when


def _showtimes(when: PartialWhen) -> tuple[clock_time, ...]:
    """The distinct start times of one date, in clock order; fewer than two is not a list."""
    times = tuple(sorted({t.replace(tzinfo=None) for t in when.showtimes}))
    return times if len(times) > 1 else ()


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def _clean_entities(entities: tuple[EntityRef, ...]) -> tuple[EntityRef, ...] | None:
    """Blank names are dropped; a control character anywhere rejects (returns None)."""
    cleaned: list[EntityRef] = []
    for entity in entities:
        if has_control_characters(entity.name):
            return None
        name = " ".join(entity.name.split())
        if name:
            cleaned.append(EntityRef(name=name, role=entity.role, origin=entity.origin))
    return tuple(cleaned)


def _screen(
    candidate: EventCandidate, title: str, entities: tuple[EntityRef, ...] | None
) -> RejectReason | None:
    """Cheap checks on the text fields, in a fixed order. None means they are fine."""
    if not title:
        return RejectReason.BLANK_TITLE
    texts = [
        title,
        candidate.summary,
        candidate.evidence,
        candidate.uid or "",
        candidate.url or "",
        candidate.city,
        candidate.price,
        candidate.age,
        *candidate.tags,
    ]
    if candidate.when is not None:
        texts.append(candidate.when.raw_text)
    if entities is None or any(has_control_characters(t) for t in texts):
        return RejectReason.CONTROL_CHARACTERS
    if len(title) > MAX_TITLE_LENGTH:
        return RejectReason.TITLE_TOO_LONG
    if not candidate.evidence.strip():
        return RejectReason.NO_EVIDENCE
    return None


def validate_candidate(
    candidate: EventCandidate,
    *,
    message_body: str,
    now: datetime,
    home_tz: str,
    check_evidence: bool,
) -> EventDraft | RejectReason:
    """Validate untrusted extractor output into an `EventDraft`, or return the reason.

    `check_evidence` demands the quoted evidence appear in `message_body` (set it for model
    output; structured data such as JSON-LD has no quotable line). A malformed URL is dropped,
    not fatal: the event is still real.
    """
    title = unicodedata.normalize("NFC", (candidate.title or "").strip())
    entities = _clean_entities(candidate.entities)
    problem = _screen(candidate, title, entities)
    if (
        problem is None
        and check_evidence
        and _squash(candidate.evidence) not in _squash(message_body)
    ):
        problem = RejectReason.EVIDENCE_NOT_IN_MESSAGE
    if problem is not None:
        return problem
    if candidate.when is None or entities is None:
        return RejectReason.MISSING_DATE
    when = resolve_when(candidate.when, now=now, home_tz=home_tz, allow_past=candidate.is_recap)
    if isinstance(when, RejectReason):
        return when
    return EventDraft(
        kind=candidate.kind or EventKind.EVENT,
        title=title,
        summary=candidate.summary.strip(),
        when=when,
        evidence=candidate.evidence.strip(),
        raw_date_text=candidate.when.raw_text,
        entities=entities,
        uid=(candidate.uid or "").strip() or None,
        sequence=max(candidate.sequence, 0),
        url=canonical_url(candidate.url) if candidate.url is not None else None,
        city=" ".join(candidate.city.split()),
        tags=frozenset(t.strip() for t in candidate.tags if t.strip()),
        price=" ".join(candidate.price.split()),
        age=" ".join(candidate.age.split()),
        night_of=local_date(when) - timedelta(days=1) if candidate.when.late_night else None,
        showtimes=_showtimes(candidate.when),
    )
