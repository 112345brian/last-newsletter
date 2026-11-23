"""Application rule: give every line of an "upcoming" window its event type, and narrow by it.

Pure, like `apply_taste`: the window in, the window out. Each line is classified from what it
already carries (title, venue categories, sources, organizers, tags, and genres when they were
looked up) by the owner's `EventTypeRules`; an organizer the `PromoterDirectory` knows contributes
its scene. With `only` empty every line is labelled and none is dropped. With types named, a line
of another type is dropped, and a line whose type is unknown is dropped *and counted* in
`event_type_unknown_hidden`: not being able to tell is never the same as being the wrong type.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from concert_tracker_core.event_types import EventFacts, EventType, EventTypeRules
from concert_tracker_core.use_cases.list_upcoming_events import UpcomingDay, UpcomingEvents

if TYPE_CHECKING:
    from collections.abc import Collection

    from concert_tracker_core.promoters import PromoterDirectory
    from concert_tracker_core.use_cases.list_upcoming_events import UpcomingEvent


@dataclass(frozen=True, slots=True)
class EventTypeScope:
    """How to type a window: the rules, the promoters they consult, and the types wanted."""

    rules: EventTypeRules
    promoters: PromoterDirectory
    only: frozenset[EventType] = frozenset()


def _facts(line: UpcomingEvent, promoters: PromoterDirectory) -> EventFacts:
    return EventFacts(
        title=line.title,
        venue=line.venue,
        venue_categories=line.venue_categories,
        sources=line.sources,
        promoter_affinities=promoters.affinities_for(line.organizers),
        genres=line.genres,
        tags=line.tags,
    )


def event_type_of(line: UpcomingEvent, scope: EventTypeScope) -> EventType:
    """The type `scope`'s rules give `line`; `UNKNOWN` when none matches."""
    return scope.rules.classify(_facts(line, scope.promoters))


def apply_event_types(upcoming: UpcomingEvents, scope: EventTypeScope) -> UpcomingEvents:
    """`upcoming` with each line typed and, when `scope.only` names types, narrowed to them.

    Lines of unknown type that a filter left out are counted in `event_type_unknown_hidden`,
    added to any count the window already carried.
    """
    wanted: Collection[EventType] = scope.only
    unknown_hidden = 0
    days: list[UpcomingDay] = []
    for day in upcoming.days:
        kept: list[UpcomingEvent] = []
        for line in day.events:
            kind = event_type_of(line, scope)
            if wanted and kind not in wanted:
                unknown_hidden += kind is EventType.UNKNOWN
                continue
            kept.append(replace(line, event_type=kind))
        if kept:
            days.append(UpcomingDay(day=day.day, events=tuple(kept)))
    return replace(
        upcoming,
        days=tuple(days),
        event_type_unknown_hidden=upcoming.event_type_unknown_hidden + unknown_hidden,
    )
