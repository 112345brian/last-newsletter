"""What kind of place a venue is, so listings can be filtered by it.

A `VenueDirectory` maps venue names to categories ("The Frida Cinema" is a cinema, "The Echo" is
a music venue; a venue may be several things). It is plain data: nothing here reads a file or
guesses. A venue the directory does not know is *unclassified*, which is an answer of its own and
never defaults to some category; callers say how many events that hid when they filter.

Names are compared through `normalize_without_leading_article`, so "The Echo", "the ECHO!" and
"Echo" are one entry. Where the data comes from (a packaged seed, the owner's own file) is the
app layer's business; core only validates the shape (`parse_venue_directory`).
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from concert_tracker_core.event_rules import normalize_without_leading_article

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


# "TBA" is the reserved value for "venue unknown" (secret and warehouse shows). It is never a venue.
UNKNOWN_VENUES = frozenset({"tba", "t b a"})  # as normalized: "TBA" and "T.B.A."


class VenueCategory(StrEnum):
    MUSIC_VENUE = "music_venue"  # a room whose main business is live bands and DJs
    CLUB = "club"  # a dance club or nightclub
    BAR = "bar"  # a bar, brewery or restaurant that hosts shows
    THEATER = "theater"  # a stage-play or performing-arts house
    CONCERT_HALL = "concert_hall"  # a recital or orchestra hall
    CINEMA = "cinema"  # a movie theater
    ARENA = "arena"  # an arena or stadium
    AMPHITHEATER = "amphitheater"  # an outdoor amphitheater or bowl
    MUSEUM_GALLERY = "museum_gallery"  # a museum, gallery or arts centre
    RECORD_STORE = "record_store"  # a shop that also hosts shows


class Screening(StrEnum):
    """What a `VenueFilter` decides about one event's venue."""

    KEEP = "keep"
    UNCLASSIFIED = "unclassified"  # the venue is not in the directory, so it cannot be judged
    EXCLUDED = "excluded"  # the venue is known and none of its categories is wanted


class VenueDirectoryError(ValueError):
    """The venue data is malformed, or two entries disagree about one venue."""


@dataclass(frozen=True, slots=True)
class VenueEntry:
    """One venue under every name it goes by, with its categories."""

    names: tuple[str, ...]
    categories: frozenset[VenueCategory]


@dataclass(frozen=True, slots=True)
class VenueDirectory:
    """Normalized venue name -> categories; build with `from_entries` or `parse_venue_directory`."""

    by_name: Mapping[str, frozenset[VenueCategory]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    @classmethod
    def from_entries(cls, entries: Iterable[VenueEntry]) -> VenueDirectory:
        table: dict[str, frozenset[VenueCategory]] = {}
        for entry in entries:
            if not entry.categories:
                msg = f"venue {entry.names!r} has no categories"
                raise VenueDirectoryError(msg)
            keys = [normalize_without_leading_article(name) for name in entry.names]
            if not keys or not all(keys):
                msg = f"venue {entry.names!r} needs at least one non-blank name"
                raise VenueDirectoryError(msg)
            for key in keys:
                if key in UNKNOWN_VENUES:
                    msg = f"venue {entry.names!r}: TBA is reserved for an unknown venue, not a name"
                    raise VenueDirectoryError(msg)
                known = table.get(key)
                if known is not None and known != entry.categories:
                    msg = (
                        f"venue name {key!r} is listed twice with different categories "
                        f"({sorted(known)} and {sorted(entry.categories)})"
                    )
                    raise VenueDirectoryError(msg)
                table[key] = entry.categories
        return cls(MappingProxyType(table))

    def categories_for(self, venue: str) -> frozenset[VenueCategory]:
        """The venue's categories; empty (unclassified) for an unknown or blank venue."""
        key = normalize_without_leading_article(venue)
        return self.by_name.get(key, frozenset()) if key else frozenset()

    def is_classified(self, venue: str) -> bool:
        return bool(self.categories_for(venue))

    def with_overrides(self, other: VenueDirectory) -> VenueDirectory:
        """A new directory where `other`'s names replace this one's; neither input changes."""
        return VenueDirectory(MappingProxyType({**self.by_name, **other.by_name}))


@dataclass(frozen=True, slots=True)
class VenueFilter:
    """A directory plus the categories wanted (any of them). No categories: label only."""

    directory: VenueDirectory
    only: frozenset[VenueCategory] = frozenset()

    def screen(self, venue: str) -> tuple[frozenset[VenueCategory], Screening]:
        categories = self.directory.categories_for(venue)
        if not self.only:
            return categories, Screening.KEEP
        if not categories:
            return categories, Screening.UNCLASSIFIED
        if categories.isdisjoint(self.only):
            return categories, Screening.EXCLUDED
        return categories, Screening.KEEP


def _string_list(value: object, what: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        msg = f"{what} must be a list of strings"
        raise VenueDirectoryError(msg)
    return [item for item in value if isinstance(item, str)]


def _category(raw: str) -> VenueCategory:
    try:
        return VenueCategory(raw)
    except ValueError:
        valid = ", ".join(c.value for c in VenueCategory)
        msg = f"unknown venue category {raw!r} (one of: {valid})"
        raise VenueDirectoryError(msg) from None


def parse_venue_directory(data: object) -> VenueDirectory:
    """Build a directory from parsed JSON: `{"venues": [{"names": [...], "categories": [...]}]}`."""
    if not isinstance(data, dict) or not isinstance(data.get("venues"), list):
        msg = 'venue data must be an object with a "venues" list'
        raise VenueDirectoryError(msg)
    entries: list[VenueEntry] = []
    for position, item in enumerate(data["venues"], start=1):
        if not isinstance(item, dict):
            msg = f"venue #{position} must be an object"
            raise VenueDirectoryError(msg)
        names = _string_list(item.get("names"), f"venue #{position} names")
        categories = _string_list(item.get("categories"), f"venue #{position} categories")
        entries.append(VenueEntry(tuple(names), frozenset(_category(raw) for raw in categories)))
    return VenueDirectory.from_entries(entries)
