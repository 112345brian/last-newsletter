"""Taste: what genre an artist is, and how much the owner has listened to them lately.

Pure rules, no I/O. The facts (an artist's genres, the owner's plays) and the ports that supply them
live in the `lastfm-taste` library (`ArtistTaste`, `TasteBook`, `ArtistTagSource`,
`ListeningHistory`); the app layer gathers the answers into a `TasteBook`. `apply_taste` then
enriches the "upcoming" window with them: each event gets its artists' genres and the plays of its
most-played billed artist, can be narrowed by genre or to artists the owner listens to, and can be
ranked by plays.

"Unknown is an answer, never a guess": an artist the source has no tags for has no genres, and
when a genre filter is on, events whose genres are unknown are left out and counted in
`taste_unknown_hidden`, so nothing disappears silently.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from concert_tracker_core.event_rules import normalize_text
from concert_tracker_core.use_cases.list_upcoming_events import UpcomingDay

if TYPE_CHECKING:
    from collections.abc import Iterable

    from lastfm_taste import ArtistTaste, TasteBook

    from concert_tracker_core.use_cases.list_upcoming_events import (
        UpcomingEvent,
        UpcomingEvents,
    )


@dataclass(frozen=True, slots=True)
class TasteFilter:
    """Which events to keep: any of `genres` (empty: any), and only artists the owner has
    listened to at least `min_plays` times when `min_plays` is set. `rank` puts the most
    listened-to events first within each day."""

    genres: frozenset[str] = frozenset()
    min_plays: int = 0
    rank: bool = False

    @classmethod
    def of(cls, genres: Iterable[str], *, min_plays: int = 0, rank: bool = False) -> TasteFilter:
        keys = frozenset(normalize_text(g) for g in genres)
        if "" in keys:
            msg = "a genre must not be blank"
            raise ValueError(msg)
        if min_plays < 0:
            msg = "min_plays must not be negative"
            raise ValueError(msg)
        return cls(keys, min_plays, rank)

    @property
    def narrows(self) -> bool:
        return bool(self.genres) or self.min_plays > 0


def _matches(taste: ArtistTaste | None, wanted: TasteFilter) -> bool | None:
    """True/False for a verdict, None when the event's artists are unknown but a genre was asked."""
    plays = taste.plays if taste else 0
    if plays < wanted.min_plays:
        return False
    if not wanted.genres:
        return True
    if taste is None or not taste.genres:
        return None
    return bool(wanted.genres & set(taste.genres))


def apply_taste(upcoming: UpcomingEvents, book: TasteBook, wanted: TasteFilter) -> UpcomingEvents:
    """`upcoming` with each line's genres and plays filled in, narrowed and ranked per `wanted`."""
    unknown = 0
    days = []
    for day in upcoming.days:
        kept: list[UpcomingEvent] = []
        for line in day.events:
            taste = book.of(line.artists)
            verdict = _matches(taste, wanted)
            if verdict is None:
                unknown += 1
                continue
            if not verdict:
                continue
            kept.append(replace(line, genres=taste.genres, plays=taste.plays) if taste else line)
        if wanted.rank:
            kept.sort(key=lambda e: -e.plays)  # stable: ties stay in time order
        if kept:
            days.append(UpcomingDay(day=day.day, events=tuple(kept)))
    return replace(
        upcoming, days=tuple(days), taste_unknown_hidden=upcoming.taste_unknown_hidden + unknown
    )
