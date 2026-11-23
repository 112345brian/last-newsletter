"""What the engine publishes: an upcoming window turned into a stable, shareable event listing.

`build_event_export` takes the window `list_upcoming_events` already produced (typed by
`apply_event_types`, venues classified) and keeps an explicit allow-list of public facts about each
event: title, when, venue, city, venue categories, event type, the sources that listed it, its URL
and its artists. Everything personal or internal is *not copied*, by construction rather than by
filtering: no listening data (genres, plays), no message ids or evidence quotes (what came out of
a mailbox), no paths. A test scans the schema and the output for those names.

Unknown is an answer: a venue, city or URL the ledger does not know is `None` (JSON `null`), never
a guess. `generated_at` is when the ledger last saw any listed event, not the wall clock, so
exporting an unchanged ledger twice gives identical bytes.

The shape is `SCHEMA_VERSION` 1; `concert_tracker_app/data/export.schema.json` describes it.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from concert_tracker_core.events import EntityRole

if TYPE_CHECKING:
    from datetime import date

    from concert_tracker_core.use_cases.list_upcoming_events import UpcomingEvent, UpcomingEvents

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class PublishedArtist:
    name: str
    role: EntityRole  # headliner or support


@dataclass(frozen=True, slots=True)
class PublishedEvent:
    event_id: str
    title: str
    day: date
    all_day: bool
    start: str | None  # ISO 8601 with the offset of the event's own zone
    end: str | None
    showtimes: tuple[str, ...]
    venue: str | None
    city: str | None
    venue_categories: tuple[str, ...]
    event_type: str
    sources: tuple[str, ...]
    url: str | None
    artists: tuple[PublishedArtist, ...]
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExportContext:
    """The facts about the run that are not about any one event."""

    time_zone: str
    region_name: str | None = None
    generated_at: datetime | None = None  # tz-aware; `None` when the ledger has nothing


@dataclass(frozen=True, slots=True)
class EventExport:
    context: ExportContext
    first_day: date
    last_day: date
    events: tuple[PublishedEvent, ...]

    def counts(self) -> dict[str, object]:
        by_type: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for event in self.events:
            by_type[event.event_type] = by_type.get(event.event_type, 0) + 1
            for source in event.sources:
                by_source[source] = by_source.get(source, 0) + 1
        return {
            "events": len(self.events),
            "by_event_type": dict(sorted(by_type.items())),
            "by_source": dict(sorted(by_source.items(), key=lambda item: item[0].casefold())),
        }


def _showtimes(line: UpcomingEvent, zone: ZoneInfo) -> tuple[str, ...]:
    if line.starts_at is None:
        return ()
    day = line.starts_at.astimezone(zone).date()
    return tuple(datetime.combine(day, clock, tzinfo=zone).isoformat() for clock in line.showtimes)


def _artists(line: UpcomingEvent) -> tuple[PublishedArtist, ...]:
    return tuple(
        PublishedArtist(
            name, EntityRole.HEADLINER if name in line.headliners else EntityRole.SUPPORT
        )
        for name in line.artists
    )


def _published(line: UpcomingEvent, zone: ZoneInfo) -> PublishedEvent:
    return PublishedEvent(
        event_id=str(line.event_id),
        title=line.title,
        day=line.day,
        all_day=line.all_day,
        start=line.starts_at.isoformat() if line.starts_at is not None else None,
        end=line.ends_at.isoformat() if line.ends_at is not None else None,
        showtimes=_showtimes(line, zone),
        venue=line.venue or None,
        city=line.city or None,
        venue_categories=tuple(sorted(c.value for c in line.venue_categories)),
        event_type=line.event_type.value,
        sources=line.sources,
        url=line.url,
        artists=_artists(line),
        tags=line.tags,
    )


def build_event_export(upcoming: UpcomingEvents, context: ExportContext) -> EventExport:
    """The allow-listed public view of `upcoming`, in the window's own order."""
    zone = ZoneInfo(context.time_zone)
    return EventExport(
        context=context,
        first_day=upcoming.first_day,
        last_day=upcoming.last_day,
        events=tuple(_published(line, zone) for day in upcoming.days for line in day.events),
    )


def _event_data(event: PublishedEvent) -> dict[str, object]:
    return {
        "id": event.event_id,
        "title": event.title,
        "date": event.day.isoformat(),
        "all_day": event.all_day,
        "start": event.start,
        "end": event.end,
        "showtimes": list(event.showtimes),
        "venue": event.venue,
        "city": event.city,
        "venue_categories": list(event.venue_categories),
        "event_type": event.event_type,
        "sources": list(event.sources),
        "url": event.url,
        "artists": [{"name": a.name, "role": a.role.value} for a in event.artists],
        "tags": list(event.tags),
    }


def export_as_data(export: EventExport) -> dict[str, object]:
    """The export as plain JSON-ready data, keys in the order the schema documents them."""
    generated = export.context.generated_at
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated.astimezone(UTC).isoformat() if generated is not None else None,
        "region": {"name": export.context.region_name, "time_zone": export.context.time_zone},
        "window": {
            "first_day": export.first_day.isoformat(),
            "last_day": export.last_day.isoformat(),
        },
        "counts": export.counts(),
        "events": [_event_data(event) for event in export.events],
    }
