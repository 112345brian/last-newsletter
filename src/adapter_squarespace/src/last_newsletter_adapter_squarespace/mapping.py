"""One Squarespace event item -> an `EventCandidate`, or the reason it is skipped.

Squarespace stores `startDate` as epoch milliseconds, a real instant, shown here in the configured
zone (checked against the times written in the listings themselves). `endDate` is not used: sites
leave it at the editor's default length, so it says nothing about when a show actually ends.

Many small venues post the lineup as the *body* and use the date as the *title* ("Thursday,
November 12, 2026"). When the title is only a date, the title is rebuilt from the item's tags
(which for such sites are the bands plus one date tag), falling back to the excerpt's lines. A
line ending "presents…" names the promoter. The room or promoter that owns the whole feed is
configuration, because the item's map location is a placeholder on many sites.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import html
import re
from dataclasses import dataclass
from datetime import datetime, time
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

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_INVISIBLE = re.compile(r"[\u200b-\u200d\u2060\ufeff\u00a0]+")
_SPACE = re.compile(r"\s+")
_BLOCKS = re.compile(r"</p>|<br\s*/?>|</li>|</div>|</h[1-6]>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_HREF = re.compile(r"""href=["'](https?://[^"']+)["']""", re.IGNORECASE)
_DATE_LIKE = re.compile(
    r"^(mon|tue|tues|wed|wednes|thu|thur|thurs|fri|sat|satur|sun)(day)?\.?,?\s+"
    r"[a-z]+\.?\s+\d{1,2}(st|nd|rd|th)?(,?\s+\d{4})?$",
    re.IGNORECASE,
)
_TIME_LINE = re.compile(r"^\d{1,2}(:\d{2})?\s*[ap]\.?m\.?(\b|$)", re.IGNORECASE)
_PRICE_LINE = re.compile(r"^(\$|free\b|no cover|donation|suggested|sliding)", re.IGNORECASE)
_TBA_LINE = re.compile(r"^more\b.*\btba\b", re.IGNORECASE)
_PRESENTS = re.compile(r"^(?P<who>.+?)\s+presents\W*$", re.IGNORECASE)
_SUMMARY_CHARS = 280
_TITLE_CHARS = 160
_MAX_BANDS = 6
_MS = 1000.0


def _text(value: object) -> str:
    cleaned = _INVISIBLE.sub(" ", _CONTROL.sub(" ", html.unescape(str(value)))) if value else ""
    return _SPACE.sub(" ", cleaned).strip()


def _lines(markup: object) -> list[str]:
    if not isinstance(markup, str):
        return []
    parts = (_text(_TAGS.sub("", chunk)) for chunk in _BLOCKS.split(markup))
    return [line for line in parts if line]


def is_date_like(text: str) -> bool:
    """ "Thursday, November 12, 2026" or "Thursday November 12 2026": a date used as a name."""
    return bool(_DATE_LIKE.match(_text(text)))


def _is_filler(line: str) -> bool:
    return bool(
        _TIME_LINE.match(line)
        or _PRICE_LINE.match(line)
        or _TBA_LINE.match(line)
        or "ticket" in line.lower()
        or _PRESENTS.match(line)
    )


def _tag_list(item: dict[str, object]) -> list[str]:
    tags = item.get("tags")
    return [_text(t) for t in tags if _text(t)] if isinstance(tags, list) else []


def _promoters(lines: list[str]) -> set[str]:
    """Names from "<who> presents…" lines, lower-cased: a promoter is not on the bill."""
    return {m.group("who").lower() for line in lines if (m := _PRESENTS.match(line))}


def _lineup(item: dict[str, object], lines: list[str]) -> list[str]:
    promoters = _promoters(lines)
    from_tags = [t for t in _tag_list(item) if not is_date_like(t) and t.lower() not in promoters]
    if from_tags:
        return from_tags[:_MAX_BANDS]
    return [line for line in lines if not _is_filler(line)][:_MAX_BANDS]


def _int(value: object) -> int | None:
    try:
        return int(str(value))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class FeedContext:
    """What a whole feed shares: its label, site, display zone, the fetch time, and the room or
    promoter that owns it."""

    name: str
    base_url: str
    tz: ZoneInfo
    now: datetime
    venue: str = ""
    organizer: str = ""


def candidate_from_item(item: dict[str, object], feed: FeedContext) -> EventCandidate | str:
    """The candidate, or a short skip reason: "no_id", "no_title" or "no_date"."""
    name, tz, now = feed.name, feed.tz, feed.now
    venue, organizer = feed.venue, feed.organizer
    item_id, raw_title = _text(item.get("id")), _text(item.get("title"))
    if not item_id:
        return "no_id"
    if not raw_title:
        return "no_title"
    start_ms = _int(item.get("startDate"))
    if start_ms is None:
        return "no_date"
    start = datetime.fromtimestamp(start_ms / _MS, tz)
    lines = _lines(item.get("excerpt"))
    dated_title = is_date_like(raw_title)
    title = " / ".join(_lineup(item, lines))[:_TITLE_CHARS] if dated_title else raw_title
    title = title or raw_title
    entities = _entities(venue, organizer, lines)
    updated = _int(item.get("updatedOn"))
    local_time = time(start.hour, start.minute)
    evidence = (
        f"{name} {item_id} | {title} | {start.date().isoformat()} "
        f"{local_time.isoformat(timespec='minutes')} | {venue or organizer}"
    )
    return EventCandidate(
        message_id=f"{name}:{item_id}",
        title=title,
        kind=EventKind.EVENT,
        summary="" if dated_title else (lines[0] if lines else "")[:_SUMMARY_CHARS],
        when=PartialWhen(
            year=start.year,
            month=start.month,
            day=start.day,
            time=local_time,
            tz=tz.key,
            raw_text=start.date().isoformat(),
        ),
        evidence=evidence,
        entities=entities,
        uid=f"{name}:{item_id}",
        sequence=int(updated / _MS) if updated is not None else int(now.timestamp()),
        url=_ticket_link(item) or _page_url(feed.base_url, item),
        tags=frozenset() if dated_title else frozenset(t.lower() for t in _tag_list(item)),
        price=next((line[:60] for line in lines if _PRICE_LINE.match(line)), ""),
    )


def _entities(venue: str, organizer: str, lines: list[str]) -> tuple[EntityRef, ...]:
    out: list[EntityRef] = []
    if venue:
        out.append(EntityRef(name=venue, role=EntityRole.VENUE))
    if organizer:
        out.append(EntityRef(name=organizer, role=EntityRole.ORGANIZER))
    for line in lines:
        match = _PRESENTS.match(line)
        if match and not organizer:
            out.append(EntityRef(name=match.group("who"), role=EntityRole.ORGANIZER))
            break
    return tuple(out)


def _ticket_link(item: dict[str, object]) -> str | None:
    for key in ("excerpt", "body"):
        value = item.get(key)
        match = _HREF.search(value) if isinstance(value, str) else None
        if match:
            return html.unescape(match.group(1))
    return None


def _page_url(base_url: str, item: dict[str, object]) -> str | None:
    path = _text(item.get("fullUrl"))
    return f"{base_url.rstrip('/')}{path}" if path.startswith("/") else None
