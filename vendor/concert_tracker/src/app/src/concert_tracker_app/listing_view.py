"""Reading views: the filtered "upcoming" list and the venue report.

Text for people, plain data for `--json`. Both only show what the ledger stores (title, venue,
city, link); never a message body. A filter that hid events says so (`unclassified_hidden` for
venues, `event_type_unknown_hidden` for event types).
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

import json
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from concert_tracker_core.event_rules import venue_key
from concert_tracker_core.event_types import EventType
from concert_tracker_core.source_runs import source_key
from concert_tracker_core.use_cases.classify_upcoming_events import (
    EventTypeScope,
    apply_event_types,
)
from concert_tracker_core.use_cases.list_upcoming_events import (
    only_from_sources,
    upcoming_from_events,
)
from concert_tracker_core.venue_categories import VenueFilter

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime, time
    from pathlib import Path

    from concert_tracker_core.event_types import EventTypeRules
    from concert_tracker_core.events import Event
    from concert_tracker_core.promoters import PromoterDirectory
    from concert_tracker_core.use_cases.list_upcoming_events import UpcomingEvent, UpcomingEvents
    from concert_tracker_core.venue_categories import VenueCategory, VenueDirectory

NO_VENUE = "(no venue)"


def _clock(value: time) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def _labels(categories: frozenset[VenueCategory]) -> list[str]:
    return sorted(c.value for c in categories)


CITY_FROM_EVENT = "event"
CITY_FROM_DIRECTORY = "venue_directory"


def _city_source(event: UpcomingEvent) -> str:
    """Where the city came from: "" when there is none, never a guess."""
    if not event.city:
        return ""
    return CITY_FROM_DIRECTORY if event.city_from_directory else CITY_FROM_EVENT


def _where(event: UpcomingEvent) -> str:
    """ " - Venue (City)", labelled "per venue directory" when the venue, not the event, gave it."""
    city = ""
    if event.city:
        note = ", per venue directory" if event.city_from_directory else ""
        city = f" ({event.city}{note})"
    return f" - {event.venue}{city}" if event.venue else f" - {event.city}" if event.city else ""


def _line(event: UpcomingEvent) -> str:
    when = "all day" if event.all_day else _clock(event.start) if event.start else "time n/a"
    where = _where(event)
    tags = f" [{', '.join(_labels(event.venue_categories))}]" if event.venue_categories else ""
    kind = f" {{{event.event_type.value}}}" if event.event_type is not EventType.UNKNOWN else ""
    genres = f" ({', '.join(event.genres)})" if event.genres else ""
    heard = f"  ★ {event.plays} plays" if event.plays else ""
    seen = f"  (via {', '.join(event.sources)})" if event.sources else ""
    return f"  {when:<9} {event.title}{where}{tags}{kind}{genres}{heard}{seen}"


@dataclass(frozen=True, slots=True)
class UpcomingScope:
    """What to narrow the window to: venue types and/or the sources that listed the events."""

    venue_filter: VenueFilter
    sources: tuple[str, ...] = ()


def scope_for(
    directory: VenueDirectory,
    venue_types: Iterable[VenueCategory],
    sources: Iterable[str] = (),
) -> UpcomingScope:
    """Tag every line with its venue's types; narrow to `venue_types` and `sources` when given."""
    return UpcomingScope(VenueFilter(directory, only=frozenset(venue_types)), tuple(sources))


def event_type_scope(
    rules: EventTypeRules, promoters: PromoterDirectory, types: Iterable[str] = ()
) -> EventTypeScope:
    """Type every line by `rules`; narrow to the named `types` (any-of) when given."""
    return EventTypeScope(rules, promoters, frozenset(EventType(t) for t in types))


def with_event_types(upcoming: UpcomingEvents, scope: EventTypeScope) -> UpcomingEvents:
    """`upcoming` with every line's event type set; when `scope` names types, a line of another
    type goes and a line of unknown type goes *and is counted* in `event_type_unknown_hidden`,
    which `render_upcoming` and `upcoming_as_data` both report."""
    return apply_event_types(upcoming, scope)


def known_sources(events: Iterable[Event]) -> list[str]:
    """Every source that has listed an event in the ledger, sorted: what `--source` accepts."""
    return sorted({m.source for e in events for m in e.mentions}, key=str.casefold)


def unknown_sources(events: Iterable[Event], wanted: Iterable[str]) -> list[str]:
    known = {source_key(name) for name in known_sources(events)}
    return [name for name in wanted if source_key(name) not in known]


def upcoming_in_scope(
    events: Iterable[Event],
    scope: UpcomingScope,
    *,
    now: datetime,
    days: int,
    tz_name: str,
) -> UpcomingEvents:
    """The window narrowed by `scope`; what it hid for an unclassified venue is counted in
    `unclassified_hidden`, which `render_upcoming` and `upcoming_as_data` both report.
    """
    return upcoming_from_events(
        only_from_sources(events, scope.sources),
        now=now,
        days=days,
        tz_name=tz_name,
        venue_filter=scope.venue_filter,
    )


def render_upcoming(upcoming: UpcomingEvents, *, credit: str = "") -> str:
    lines: list[str] = []
    for day in upcoming.days:
        lines.append(day.day.strftime("%a %b %d"))
        lines.extend(_line(event) for event in day.events)
        lines.append("")
    lines.append(
        f"{upcoming.event_count} event(s), {upcoming.first_day.strftime('%b %d')} to "
        f"{upcoming.last_day.strftime('%b %d')}."
    )
    if upcoming.unclassified_hidden:
        lines.append(
            f"{upcoming.unclassified_hidden} more not shown: their venue is not classified "
            "(run `concert-tracker venues` to see which)."
        )
    if upcoming.event_type_unknown_hidden:
        lines.append(
            f"{upcoming.event_type_unknown_hidden} more not shown: their event type is unknown "
            "(add rules to event_types.json in your data directory, or ask for "
            "`--event-type unknown` to see them)."
        )
    if upcoming.taste_unknown_hidden:
        lines.append(
            f"{upcoming.taste_unknown_hidden} more not shown: their artists' genres are unknown."
        )
    if credit:
        lines.append(credit)
    return "\n".join(lines)


def upcoming_as_data(upcoming: UpcomingEvents) -> dict[str, Any]:
    return {
        "first_day": upcoming.first_day.isoformat(),
        "last_day": upcoming.last_day.isoformat(),
        "event_count": upcoming.event_count,
        "unclassified_hidden": upcoming.unclassified_hidden,
        "event_type_unknown_hidden": upcoming.event_type_unknown_hidden,
        "taste_unknown_hidden": upcoming.taste_unknown_hidden,
        "days": [
            {
                "day": day.day.isoformat(),
                "events": [
                    {
                        "id": str(e.event_id),
                        "title": e.title,
                        "venue": e.venue,
                        "city": e.city,
                        "city_source": _city_source(e),
                        "venue_categories": _labels(e.venue_categories),
                        "event_type": e.event_type.value,
                        "all_day": e.all_day,
                        "start": e.start.isoformat() if e.start else None,
                        "end": e.end.isoformat() if e.end else None,
                        "url": e.url,
                        "mention_count": e.mention_count,
                        "sources": list(e.sources),
                        "artists": list(e.artists),
                        "genres": list(e.genres),
                        "plays": e.plays,
                    }
                    for e in day.events
                ],
            }
            for day in upcoming.days
        ],
    }


def render_upcoming_json(upcoming: UpcomingEvents) -> str:
    return json.dumps(upcoming_as_data(upcoming), indent=2, ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class VenueRow:
    name: str  # as first seen, or NO_VENUE for a blank or "TBA" (unknown) venue
    events: int
    categories: frozenset[VenueCategory]


def venue_rows(events: list[Event], directory: VenueDirectory) -> list[VenueRow]:
    """One row per distinct venue (by normalized name), unclassified first, then busiest."""
    counts: Counter[str] = Counter()
    first_seen: dict[str, str] = {}
    for event in events:
        key = venue_key(event.venue)
        counts[key] += 1
        first_seen.setdefault(key, event.venue if key else NO_VENUE)
    rows = [
        VenueRow(
            first_seen[key], n, directory.categories_for(first_seen[key]) if key else frozenset()
        )
        for key, n in counts.items()
    ]
    return sorted(rows, key=lambda r: (bool(r.categories), -r.events, r.name.casefold()))


def render_venue_report(rows: list[VenueRow], owner_file: Path) -> str:
    lines = [
        f"  {row.events:>3}  {row.name:<42} "
        f"{', '.join(_labels(row.categories)) if row.categories else 'unclassified'}"
        for row in rows
    ]
    missing = sum(1 for row in rows if not row.categories)
    lines.append("")
    lines.append(
        f"{missing} of {len(rows)} venue names are unclassified. Add them to {owner_file} "
        '(same shape as the packaged venues.json: {"venues": [{"names": [...], '
        '"categories": [...]}]}).'
    )
    return "\n".join(lines)
