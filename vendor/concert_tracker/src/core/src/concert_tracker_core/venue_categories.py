"""What kind of place a venue is, and where, so listings can be filtered and located.

A `VenueDirectory` maps venue names to categories ("The Sample Cinema" is a cinema,
"The Example Hall" is a music venue; a venue may be several things). It is plain data: nothing here
reads a file or guesses. A venue the directory does not know is *unclassified*, which is an
answer of its own and never defaults to some category; callers say how many events that hid
when they filter.

An entry may also say where the venue is (`city`, optionally `address`). That is a fact about the
venue, used only to fill in an event's missing city; an unknown venue has no place, and a venue
listed without a city simply has none (never guessed).

Names are compared through `venue_key` (`normalize_without_leading_article`, with "TBA" and the
other unknown-venue spellings read as no venue at all), so "The Example",
"the EXAMPLE!" and "Example" are one entry. Where the data comes from (a packaged seed, the
owner's own file) is the app layer's business; core only validates the shape
(`parse_venue_directory`).
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from concert_tracker_core.event_rules import venue_key
from concert_tracker_core.events import has_control_characters

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

_MAX_PLACE_LENGTH = 200


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
class VenuePlace:
    """Where a venue is. Either part may be blank, which means unknown (never "somewhere")."""

    city: str = ""
    address: str = ""

    def __bool__(self) -> bool:
        return bool(self.city or self.address)


@dataclass(frozen=True, slots=True)
class VenueEntry:
    """One venue under every name it goes by, with its categories and (optionally) its place."""

    names: tuple[str, ...]
    categories: frozenset[VenueCategory]
    city: str = ""
    address: str = ""


def _clean_place(entry: VenueEntry) -> VenuePlace:
    city, address = " ".join(entry.city.split()), " ".join(entry.address.split())
    for label, text in (("city", city), ("address", address)):
        if len(text) > _MAX_PLACE_LENGTH or has_control_characters(text):
            msg = f"venue {entry.names!r}: {label} is too long or has control characters"
            raise VenueDirectoryError(msg)
    if city and not venue_key(city):
        msg = f"venue {entry.names!r}: a city cannot be {city!r}; leave it out when unknown"
        raise VenueDirectoryError(msg)
    return VenuePlace(city, address)


def _record_place(places: dict[str, VenuePlace], key: str, place: VenuePlace) -> None:
    """Remember `place` for `key`. Two entries for one venue may each know part of it, but may
    not name two different cities or addresses."""
    known = places.get(key, VenuePlace())
    for label, old, new in (
        ("city", known.city, place.city),
        ("address", known.address, place.address),
    ):
        if old and new and old.casefold() != new.casefold():
            msg = f"venue name {key!r} is listed twice with a different {label} ({old!r}, {new!r})"
            raise VenueDirectoryError(msg)
    merged = VenuePlace(known.city or place.city, known.address or place.address)
    if merged:
        places[key] = merged


def _check_name(entry: VenueEntry) -> list[str]:
    """The entry's normalized names. A name that is only "TBA"/"TBD"/"(no venue)" is refused."""
    keys: list[str] = []
    for name in entry.names:
        key = venue_key(name)
        if not key:
            reason = (
                "TBA is reserved for an unknown venue, not a name"
                if name.strip()
                else "needs at least one non-blank name"
            )
            msg = f"venue {entry.names!r}: {reason}"
            raise VenueDirectoryError(msg)
        keys.append(key)
    if not keys:
        msg = f"venue {entry.names!r} needs at least one non-blank name"
        raise VenueDirectoryError(msg)
    return keys


@dataclass(frozen=True, slots=True)
class VenueDirectory:
    """Normalized venue name -> categories (and place); build with `from_entries` or
    `parse_venue_directory`."""

    by_name: Mapping[str, frozenset[VenueCategory]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    place_by_name: Mapping[str, VenuePlace] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def from_entries(cls, entries: Iterable[VenueEntry]) -> VenueDirectory:
        table: dict[str, frozenset[VenueCategory]] = {}
        places: dict[str, VenuePlace] = {}
        for entry in entries:
            if not entry.categories:
                msg = f"venue {entry.names!r} has no categories"
                raise VenueDirectoryError(msg)
            place = _clean_place(entry)
            for key in _check_name(entry):
                known = table.get(key)
                if known is not None and known != entry.categories:
                    msg = (
                        f"venue name {key!r} is listed twice with different categories "
                        f"({sorted(known)} and {sorted(entry.categories)})"
                    )
                    raise VenueDirectoryError(msg)
                table[key] = entry.categories
                _record_place(places, key, place)
        return cls(MappingProxyType(table), MappingProxyType(places))

    def categories_for(self, venue: str) -> frozenset[VenueCategory]:
        """The venue's categories; empty (unclassified) for an unknown or blank venue."""
        key = venue_key(venue)
        return self.by_name.get(key, frozenset()) if key else frozenset()

    def place_for(self, venue: str) -> VenuePlace:
        """Where the venue is; an empty place for an unknown, blank or place-less venue."""
        key = venue_key(venue)
        return self.place_by_name.get(key, VenuePlace()) if key else VenuePlace()

    def is_classified(self, venue: str) -> bool:
        return bool(self.categories_for(venue))

    def with_overrides(self, other: VenueDirectory) -> VenueDirectory:
        """A new directory where `other`'s names replace this one's; neither input changes.

        A name `other` lists with a city or address replaces this one's place; one it lists
        without keeps this one's, so correcting a category never drops the city."""
        return VenueDirectory(
            MappingProxyType({**self.by_name, **other.by_name}),
            MappingProxyType({**self.place_by_name, **other.place_by_name}),
        )


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


def _optional_text(item: Mapping[str, object], key: str, position: int) -> str:
    value = item.get(key, "")
    if not isinstance(value, str):
        msg = f"venue #{position} {key} must be text"
        raise VenueDirectoryError(msg)
    return value


def parse_venue_directory(data: object) -> VenueDirectory:
    """Build a directory from parsed JSON:
    `{"venues": [{"names": [...], "categories": [...], "city": "...", "address": "..."}]}`.
    `city` and `address` are optional."""
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
        entries.append(
            VenueEntry(
                tuple(names),
                frozenset(_category(raw) for raw in categories),
                _optional_text(item, "city", position),
                _optional_text(item, "address", position),
            )
        )
    return VenueDirectory.from_entries(entries)
