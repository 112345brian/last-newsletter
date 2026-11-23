"""Turn what a title says into entities: the artists on the bill and the promoter who presents it.

`parse_title` reads a title; this module decides what of that reading becomes an `EntityRef`.
The rules are about trust, not parsing:

* A source that already named artists (Ticketmaster, Dice, ...) is never second-guessed: if the
  event has any headliner or support, nothing is added.
* A title no pattern fits adds nothing ("unknown is an answer, never guessed").
* A name that still holds a "Series: thing" or "A - B" split is two things, not a name, and a
  guest at a named series night ("Heavy Karaoke w/ Jack") is a host, not a billed artist.
* A name that is the venue, a promoter (one the parser found or the directory knows), an organizer
  the source gave, or the reserved "TBA" is never made an artist, however the title is shaped.
* Parsed entities are appended after the ones the source gave, never replacing them, and a
  second pass over the result adds nothing (so a backfill can be run again).

The event name the parser may find ("Night 2", "The Reunion Tour") has no entity role, so it
stays in the title and is not stored separately.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

import re
from typing import TYPE_CHECKING

from concert_tracker_core.event_rules import normalize_without_leading_article
from concert_tracker_core.events import EntityRef, EntityRole
from concert_tracker_core.promoters import MAX_NAME_CHARS, RESERVED_UNKNOWN
from concert_tracker_core.title_parsing import ParsedTitle, TitlePattern, parse_title

if TYPE_CHECKING:
    from collections.abc import Iterable

    from concert_tracker_core.promoters import PromoterDirectory

ARTIST_ROLES = (EntityRole.HEADLINER, EntityRole.SUPPORT)
_NO_NAMES = frozenset({"", RESERVED_UNKNOWN})
_EVENING = re.compile(r"\bevening\b", re.IGNORECASE)


def has_artist(entities: Iterable[EntityRef]) -> bool:
    """True when some entity is a headliner or a support."""
    return any(entity.role in ARTIST_ROLES for entity in entities)


def _key(name: str) -> str:
    return normalize_without_leading_article(name)


def _usable(name: str, taken: set[str], promoters: PromoterDirectory) -> bool:
    """A name worth keeping as an artist: not blank, not too long, not already used as a venue,
    organizer or earlier artist, not a promoter the directory knows."""
    key = _key(name)
    if key in _NO_NAMES or key in taken or len(name) > MAX_NAME_CHARS:
        return False
    if " - " in name or ": " in name:
        return False
    return promoters.find(name) is None


def entities_with_title_artists(
    title: str, entities: tuple[EntityRef, ...], promoters: PromoterDirectory
) -> tuple[EntityRef, ...]:
    """`entities` plus the artists and promoter the title names, or `entities` itself unchanged
    when the source already gave artists, the title is not recognised, or it adds nothing."""
    if has_artist(entities):
        return entities
    parsed = parse_title(title)
    if not parsed.headliners or _is_series_guest(parsed):
        return entities
    taken = {_key(e.name) for e in entities if e.role in (EntityRole.VENUE, EntityRole.ORGANIZER)}
    if parsed.promoter is not None:
        taken.add(_key(parsed.promoter))
    added: list[EntityRef] = []
    for role, names in (
        (EntityRole.HEADLINER, parsed.headliners),
        (EntityRole.SUPPORT, parsed.supports),
    ):
        for name in names:
            if _usable(name, taken, promoters):
                taken.add(_key(name))
                added.append(EntityRef(name=name, role=role))
    if not added:
        return entities
    organizer = _organizer_to_add(parsed.promoter, entities)
    return (*entities, *added, *organizer)


def _is_series_guest(parsed: ParsedTitle) -> bool:
    """`<series night> w/ <guest>`: the parser puts the guest first and keeps the series name as
    the event name, but nothing says the guest is an act rather than a host. "A lo-fi evening
    with X" is the exception: that idiom bills X."""
    return (
        parsed.pattern is TitlePattern.WITH_SUPPORT
        and parsed.event_name is not None
        and _EVENING.search(parsed.event_name) is None
        and not parsed.supports
    )


def _organizer_to_add(promoter: str | None, entities: tuple[EntityRef, ...]) -> list[EntityRef]:
    """The promoter as an organizer, unless unnamed, reserved, or already one of the entities
    (as a venue or an organizer)."""
    if promoter is None or _key(promoter) in _NO_NAMES or len(promoter) > MAX_NAME_CHARS:
        return []
    named = {_key(e.name) for e in entities if e.role in (EntityRole.VENUE, EntityRole.ORGANIZER)}
    if _key(promoter) in named:
        return []
    return [EntityRef(name=promoter, role=EntityRole.ORGANIZER)]
