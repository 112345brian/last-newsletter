"""Taste: what genre an artist is, and how much the owner has listened to them lately.

Pure rules, no I/O. Two ports say where the facts come from (`ArtistTagSource`: crowd tags for an
artist; `ListeningHistory`: play counts over a recent period); an adapter implements each and the
caller gathers the answers into a `TasteBook`, keyed by `artist_key`.

"Unknown is an answer, never a guess": an artist the source has no tags for has no genres, and a
source that could not answer raises `TasteSourceError` instead of reporting "no genres".
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from lastfm_taste.names import normalize_text, normalize_without_leading_article

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

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


class TasteConfigurationError(ValueError):
    """The caller asked for something that can never work (a blank key or user, an unsupported
    period). Unlike `TasteSourceError` it is permanent: retrying will not help."""


class TagStore(Protocol):
    """Where tag answers are remembered. `found=False` remembers "the source has no such artist"."""

    def get(self, key: str) -> tuple[bool, list[tuple[str, int]]] | None:
        """`(found, tags)` when a fresh answer is stored under `key`, else `None`."""
        ...

    def put(self, key: str, *, found: bool, tags: list[tuple[str, int]]) -> None: ...


class ArtistTagSource(Protocol):
    def tags(self, artist: str) -> list[tuple[str, int]] | None:
        """`(tag, weight 0-100)` pairs, strongest first; `None` when the artist is unknown to it.

        Raises `TasteSourceError` when it could not answer.
        """
        ...


class ListeningHistory(Protocol):
    def play_counts(self, months: int) -> dict[str, int]:
        """Plays per artist name over the last `months` months.

        Raises `TasteSourceError` when the history could not be read in full, and
        `TasteConfigurationError` when the source does not offer that period.
        """
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
    """What is known about one artist. Both facts are stated, never defaulted: an artist the
    sources know nothing about is absent from the `TasteBook`, not present with empty facts.

    `genres=()` means "known, and no genre survived cleaning"; `plays=0` means "known, and not
    listened to in the period".
    """

    genres: tuple[str, ...]
    plays: int

    def __post_init__(self) -> None:
        if self.plays < 0:
            msg = "plays must not be negative"
            raise ValueError(msg)


def _merged(first: ArtistTaste, second: ArtistTaste) -> ArtistTaste:
    genres = list(first.genres)
    genres.extend(g for g in second.genres if g not in genres)
    return ArtistTaste(tuple(genres), first.plays + second.plays)


@dataclass(frozen=True, slots=True)
class TasteBook:
    """What is known about artists, by `artist_key`. An artist not in it is unknown.

    Build it with `TasteBook.from_names`, which does the keying. The constructor takes ready
    keys and refuses a blank key or one that is not in normalized form (a raw "The Echo").
    """

    artists: Mapping[str, ArtistTaste]

    def __post_init__(self) -> None:
        for key in self.artists:
            if not key or normalize_text(key) != key:
                msg = f"{key!r} is not an artist_key; build the book with TasteBook.from_names"
                raise ValueError(msg)
        object.__setattr__(self, "artists", MappingProxyType(dict(self.artists)))

    @classmethod
    def from_names(cls, entries: Iterable[tuple[str, ArtistTaste]]) -> TasteBook:
        """A book from `(artist name, taste)` pairs. Names that share an `artist_key` ("The X"
        and "X") are one artist: their genres are joined and their plays added, never dropped.
        A blank name is skipped: it names no artist."""
        merged: dict[str, ArtistTaste] = {}
        for name, taste in entries:
            key = artist_key(name)
            if not key:
                continue
            merged[key] = _merged(merged[key], taste) if key in merged else taste
        return cls(merged)

    def of(self, names: Iterable[str]) -> ArtistTaste | None:
        """The taste of artists billed together as `names`: their genres together, the plays of
        the most played of them. `None` when none of the names is known."""
        known = [self.artists[k] for name in names if (k := artist_key(name)) in self.artists]
        if not known:
            return None
        genres: list[str] = []
        for taste in known:
            genres.extend(g for g in taste.genres if g not in genres)
        return ArtistTaste(tuple(genres), max(t.plays for t in known))
