"""Taste: what genre an artist is, and how much the owner has listened to them lately.

Pure rules, no I/O. Two ports say where the facts come from (`ArtistTagSource`: crowd tags for an
artist; `ListeningHistory`: play counts over a recent period); an adapter implements each and the
app layer gathers the answers into a `TasteBook`. `apply_taste` then enriches the "upcoming"
window with them: each event gets its artists' genres and the plays of its most-played billed
artist, can be narrowed by genre or to artists the owner listens to, and can be ranked by plays.

"Unknown is an answer, never a guess": an artist the source has no tags for has no genres, and
when a genre filter is on, events whose genres are unknown are left out and counted in
`taste_unknown_hidden`, so nothing disappears silently.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from concert_tracker_core.event_rules import normalize_text, normalize_without_leading_article
from concert_tracker_core.use_cases.list_upcoming_events import UpcomingDay

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from concert_tracker_core.use_cases.list_upcoming_events import (
        UpcomingEvent,
        UpcomingEvents,
    )

MAX_GENRES = 5
MIN_TAG_WEIGHT = 10  # of 100, relative to the artist's top tag; weaker tags are noise
# Tags that say who listens or what a person did with a record, not what the music is.
NOISE_TAGS = frozenset(
    {
        "seen live",
        "favorites",
        "favourites",
        "favorite",
        "favourite",
        "love",
        "loved",
        "awesome",
        "good",
        "best",
        "my music",
        "spotify",
        "albums i own",
        "male vocalists",
        "female vocalists",
        "usa",
        "american",
        "british",
        "united states",
        "los angeles",
        "california",
        "legend",
        "under 2000 listeners",
    }
)


class TasteSourceError(Exception):
    """A taste source could not answer right now (network, rate limit, bad key).

    The answer is unknown, not "no": callers must not record it as an artist with no genres.
    """


class ArtistTagSource(Protocol):
    def tags(self, artist: str) -> list[tuple[str, int]] | None:
        """`(tag, weight 0-100)` pairs, strongest first; `None` when the artist is unknown to it.

        Raises `TasteSourceError` when it could not answer.
        """
        ...


class ListeningHistory(Protocol):
    def play_counts(self, months: int) -> dict[str, int]:
        """Plays per artist name over the last `months` months. Raises `TasteSourceError`."""
        ...


def artist_key(name: str) -> str:
    """How artist names are compared: "The Microblades" and "microblades!" are one artist."""
    return normalize_without_leading_article(name)


def clean_genres(
    tags: Iterable[tuple[str, int]], artist: str = "", limit: int = MAX_GENRES
) -> tuple[str, ...]:
    """The genres among crowd `tags`: weak, noise, year-like and artist-name tags are dropped."""
    own = artist_key(artist)
    genres: list[str] = []
    for raw, weight in tags:
        tag = normalize_text(raw)
        if (
            not tag
            or weight < MIN_TAG_WEIGHT
            or tag in NOISE_TAGS
            or tag.replace(" ", "").isdigit()
            or (own and artist_key(tag) == own)
            or tag in genres
        ):
            continue
        genres.append(tag)
        if len(genres) == limit:
            break
    return tuple(genres)


@dataclass(frozen=True, slots=True)
class ArtistTaste:
    genres: tuple[str, ...] = ()
    plays: int = 0

    def __post_init__(self) -> None:
        if self.plays < 0:
            msg = "plays must not be negative"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TasteBook:
    """What is known about artists, by `artist_key`. An artist not in it is unknown."""

    artists: Mapping[str, ArtistTaste]

    def of(self, names: Iterable[str]) -> ArtistTaste | None:
        """The taste of an event billing `names`: their genres together, the plays of the most
        played of them. `None` when none of the names is known."""
        known = [self.artists[k] for name in names if (k := artist_key(name)) in self.artists]
        if not known:
            return None
        genres: list[str] = []
        for taste in known:
            genres.extend(g for g in taste.genres if g not in genres)
        return ArtistTaste(tuple(genres), max(t.plays for t in known))


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
