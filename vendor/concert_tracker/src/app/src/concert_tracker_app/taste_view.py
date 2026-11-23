"""Gathering taste for the artists in the upcoming window, and applying it.

`build_taste_book` is the only place that talks to the taste ports. It asks for each distinct
artist once (the adapter caches), turns crowd tags into genres, and joins the owner's play counts.
A lookup that failed leaves that artist unknown, counted in `TasteReport.lookup_failures`, and
`taste_unknown_hidden` on the window says how many events a genre filter left out for lack of
genres: nothing is dropped silently. Several failures in a row mean the source is down or the key
is wrong, so the run stops instead of making a hundred more doomed requests.
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

from dataclasses import dataclass
from typing import TYPE_CHECKING

from lastfm_taste import ArtistTaste, TasteBook, TasteSourceError, artist_key, clean_genres

from concert_tracker_core.taste import TasteFilter, apply_taste

if TYPE_CHECKING:
    from collections.abc import Iterable

    from lastfm_taste import ArtistTagSource, ListeningHistory

    from concert_tracker_core.use_cases.list_upcoming_events import UpcomingEvents

CONSECUTIVE_FAILURES_BEFORE_GIVING_UP = 3
CREDIT = "Genres and listening data from Last.fm (https://www.last.fm)."


@dataclass(frozen=True, slots=True)
class TasteReport:
    book: TasteBook
    lookup_failures: int = 0


def artists_in(upcoming: UpcomingEvents) -> list[str]:
    """Every distinct artist billed in the window (one spelling per `artist_key`), in order."""
    seen: dict[str, str] = {}
    for day in upcoming.days:
        for line in day.events:
            for name in line.artists:
                seen.setdefault(artist_key(name), name)
    return [name for key, name in seen.items() if key]


def build_taste_book(
    artists: Iterable[str],
    tags: ArtistTagSource | None,
    history: ListeningHistory | None,
    months: int,
) -> TasteReport:
    """Genres from `tags` (when given) and plays from `history` (when given), per artist.

    A failing `history` raises `TasteSourceError`: whoever asked for listening must not silently
    get an unranked list. A failing tag lookup only leaves that artist's genres unknown.
    """
    names = {artist_key(a): a for a in artists if artist_key(a)}
    plays: dict[str, int] = {}
    if history is not None:
        for name, count in history.play_counts(months).items():
            key = artist_key(name)
            plays[key] = plays.get(key, 0) + count
    genres: dict[str, tuple[str, ...]] = {}
    failures = 0
    streak = 0
    if tags is not None:
        for key, name in names.items():
            try:
                found = tags.tags(name)
            except TasteSourceError as error:
                failures += 1
                streak += 1
                if streak >= CONSECUTIVE_FAILURES_BEFORE_GIVING_UP:
                    msg = f"giving up after {streak} failed lookups in a row: {error}"
                    raise TasteSourceError(msg) from None
                continue
            streak = 0
            if found is not None:
                genres[key] = clean_genres(found, artist=name)
    book = TasteBook.from_names(
        (name, ArtistTaste(genres.get(key, ()), plays.get(key, 0)))
        for key, name in names.items()
        if key in genres or key in plays
    )
    return TasteReport(book, failures)


def with_taste(
    upcoming: UpcomingEvents,
    tags: ArtistTagSource | None,
    history: ListeningHistory | None,
    wanted: TasteFilter,
    months: int,
) -> tuple[UpcomingEvents, TasteReport]:
    """`upcoming` enriched and narrowed by `wanted`; `taste_unknown_hidden` reports what a genre
    filter left out for lack of genres."""
    report = build_taste_book(artists_in(upcoming), tags, history, months)
    return apply_taste(upcoming, report.book, wanted), report
