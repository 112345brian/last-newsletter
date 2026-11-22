"""The promoter directory (docs/design/promoter-directory.md): which organizers we recognise, under
which spellings, and what scene each belongs to. Frozen data and pure functions, no I/O.

Names compare through `normalize_without_leading_article`, as venue names do. Untrusted input
(a seed file, the owner's file) comes in through `parse_promoter_directory`, which raises
`ValueError` naming the entry at fault.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from concert_tracker_core.event_rules import normalize_without_leading_article
from concert_tracker_core.events import EntityRole, has_control_characters

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from concert_tracker_core.events import EntityRef

MAX_NAME_CHARS = 200
RESERVED_UNKNOWN = "tba"
"""Normalized form of "TBA", which means "unknown" everywhere in this project: never a name."""


class Affinity(StrEnum):
    """A scene or genre family a promoter is known for. Add members only when a source supports
    them; the values are what files spell."""

    ELECTRONIC = "electronic"


def _invalid(message: str) -> ValueError:
    """The one error every bad input raises, whatever its Python type was."""
    return ValueError(message)


def _check_name(name: object, what: str) -> str:
    if not isinstance(name, str):
        msg = f"promoter {what} must be text, got {type(name).__name__}"
        raise _invalid(msg)
    if has_control_characters(name):
        msg = f"promoter {what} must not contain control characters"
        raise _invalid(msg)
    if len(name) > MAX_NAME_CHARS:
        msg = f"promoter {what} is longer than {MAX_NAME_CHARS} characters"
        raise _invalid(msg)
    key = normalize_without_leading_article(name)
    if not key:
        msg = f"promoter {what} must not be blank"
        raise _invalid(msg)
    if key.removeprefix("the ") == RESERVED_UNKNOWN:
        msg = f"promoter {what} {name!r} is the reserved 'unknown' value, not a name"
        raise _invalid(msg)
    return key


@dataclass(frozen=True, slots=True)
class Promoter:
    """One promoter: a canonical `name`, other spellings of the same promoter in `aliases`
    (an alias that normalizes to the name or to an earlier alias is dropped), and the scenes it
    is known for."""

    name: str
    aliases: tuple[str, ...] = ()
    affinities: frozenset[Affinity] = frozenset()

    def __post_init__(self) -> None:
        seen = {_check_name(self.name, "name")}
        kept: list[str] = []
        for alias in self.aliases:
            key = _check_name(alias, "alias")
            if key not in seen:
                seen.add(key)
                kept.append(alias)
        if not self.affinities:
            msg = f"promoter {self.name!r} needs at least one affinity"
            raise _invalid(msg)
        object.__setattr__(self, "aliases", tuple(kept))

    @property
    def keys(self) -> frozenset[str]:
        """Every normalized spelling this promoter answers to."""
        return frozenset(normalize_without_leading_article(n) for n in (self.name, *self.aliases))


class PromoterDirectory:
    """Promoters by every spelling. Two promoters may not share a normalized spelling."""

    def __init__(self, promoters: Iterable[Promoter]) -> None:
        self._promoters: tuple[Promoter, ...] = tuple(promoters)
        by_key: dict[str, Promoter] = {}
        for promoter in self._promoters:
            for key in promoter.keys:
                other = by_key.get(key)
                if other is not None:
                    msg = (
                        f"promoter name {key!r} belongs to both {other.name!r} and "
                        f"{promoter.name!r}"
                    )
                    raise _invalid(msg)
                by_key[key] = promoter
        self._by_key = by_key

    def __len__(self) -> int:
        return len(self._promoters)

    def __iter__(self) -> Iterator[Promoter]:
        return iter(self._promoters)

    def find(self, name: str) -> Promoter | None:
        """The promoter that answers to `name`, or None (blank, odd or unknown names included)."""
        return self._by_key.get(normalize_without_leading_article(name))

    def promoters_for(self, entities: Iterable[EntityRef]) -> tuple[Promoter, ...]:
        """The distinct promoters among the organizer-role entities, in the order first named."""
        found: dict[str, Promoter] = {}
        for entity in entities:
            if entity.role is EntityRole.ORGANIZER:
                promoter = self.find(entity.name)
                if promoter is not None:
                    found.setdefault(promoter.name, promoter)
        return tuple(found.values())

    def affinities_for(self, names: Iterable[str]) -> frozenset[Affinity]:
        """The union of the affinities of every recognised name; unknown names add nothing."""
        out: set[Affinity] = set()
        for name in names:
            promoter = self.find(name)
            if promoter is not None:
                out |= promoter.affinities
        return frozenset(out)

    def with_overrides(self, other: PromoterDirectory) -> PromoterDirectory:
        """This directory with `other`'s promoters added; any promoter here that shares a
        spelling with one of them is dropped whole (the override wins)."""
        taken = {key for p in other for key in p.keys}
        kept = [p for p in self._promoters if not (p.keys & taken)]
        return PromoterDirectory([*kept, *other])


def _entry(raw: object, where: str) -> Promoter:
    if not isinstance(raw, dict):
        msg = f"promoter entry {where} must be an object"
        raise _invalid(msg)
    aliases = raw.get("aliases", [])
    affinities = raw.get("affinities")
    if not isinstance(aliases, list):
        msg = f"promoter entry {where}: aliases must be a list"
        raise _invalid(msg)
    if not isinstance(affinities, list) or not affinities:
        msg = f"promoter entry {where}: affinities must be a non-empty list"
        raise _invalid(msg)
    try:
        parsed = frozenset(Affinity(a) for a in affinities)
        return Promoter(raw.get("name"), tuple(aliases), parsed)  # ty: ignore[invalid-argument-type]
    except ValueError as exc:
        msg = f"promoter entry {where}: {exc}"
        raise _invalid(msg) from exc


def parse_promoter_directory(data: object) -> PromoterDirectory:
    """Build a directory from `{"promoters": [{"name", "aliases"?, "affinities"}, ...]}`."""
    if not isinstance(data, dict) or not isinstance(data.get("promoters"), list):
        msg = 'promoter directory must be an object with a "promoters" list'
        raise _invalid(msg)
    entries = [_entry(raw, f"promoters[{i}]") for i, raw in enumerate(data["promoters"])]
    return PromoterDirectory(entries)
