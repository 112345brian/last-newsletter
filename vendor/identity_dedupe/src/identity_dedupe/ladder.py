"""Collapse copies of one item, keeping the most complete, by an identity ladder.

Pure: no I/O, no clock. The URL normalizer is injected, and the items are anything that satisfies :class:`Dedupable`.

Two items are the same when they share an id, a producer-supplied ``canonical_key`` or a normalized resolved URL, or
(the weakest evidence) the same ``identity`` (an owner and a title). A title alone is only trusted between *loose*
copies (``is_direct`` False). A *direct* item is one the owner published itself, where every id is a distinct slot and
one title routinely covers many of them, so:

* direct items never merge with each other by title;
* a loose copy folds into a direct item only when exactly one direct item carries that title (it is that item's
  copy); when several do, the copy stays its own row rather than being guessed onto one of them -- showing a
  duplicate is the safe failure, hiding a live item is not;
* loose copies fold into each other.

Direct items are placed first so the outcome does not depend on input order; survivors come back in the order their
group first appeared.
"""
from __future__ import annotations

__arbor__ = {"ring": "core"}

from collections.abc import Callable, Iterable
from typing import Protocol, TypeVar


class Dedupable(Protocol):
    """The fields the ladder reads from an item."""

    @property
    def id(self) -> str: ...
    @property
    def canonical_key(self) -> str: ...
    @property
    def resolved_url(self) -> str | None: ...
    @property
    def is_direct(self) -> bool: ...
    @property
    def identity(self) -> tuple[str, str]:
        """``(owner, title)``, already normalized; a blank half means there is no title evidence."""
        ...
    @property
    def detail_score(self) -> tuple[int, ...]:
        """Completeness rank: the larger tuple survives when copies collapse."""
        ...


T = TypeVar("T", bound=Dedupable)


class _TitleGroup:
    """The slots one owner + title identity has produced so far."""

    __slots__ = ("direct", "loose")

    def __init__(self) -> None:
        self.direct: list[int] = []  # one slot per direct item
        self.loose: list[int] = []   # the one slot loose copies fold into


def dedupe(items: Iterable[T], *, normalize_url: Callable[[str], str]) -> list[T]:
    """Collapse copies of one item, retaining the most complete one."""
    return [survivor for survivor, _members in dedupe_grouped(items, normalize_url=normalize_url)]


def dedupe_grouped(items: Iterable[T], *, normalize_url: Callable[[str], str]) -> list[tuple[T, tuple[T, ...]]]:
    """``dedupe`` that also returns every copy folded into each survivor.

    ``members`` includes the survivor itself, in input order, so a caller that needs what the dropped copies knew
    can still read it.
    """
    listed = list(items)
    slots: list[T] = []
    members: list[list[int]] = []
    first_position: list[int] = []
    slot_by_id: dict[str, int] = {}
    canonical_slots: dict[str, int] = {}
    resolved_slots: dict[str, int] = {}
    groups_by_owner: dict[str, dict[str, _TitleGroup]] = {}

    # sorted() is stable: direct rows first, each half in input order.
    for position in sorted(range(len(listed)), key=lambda i: not listed[i].is_direct):
        item = listed[position]
        direct = item.is_direct
        canonical = item.canonical_key or None
        resolved_key = normalize_url(item.resolved_url) if item.resolved_url else None

        index = slot_by_id.get(item.id)
        if index is None and canonical:
            index = canonical_slots.get(canonical)
        if index is None and resolved_key:
            index = resolved_slots.get(resolved_key)

        group: _TitleGroup | None = None
        if index is None:
            owner, title = item.identity
            if owner and title:
                groups = groups_by_owner.setdefault(owner, {})
                key = next((seen for seen in groups if seen == title or _same_title_variant(seen, title)), title)
                group = groups.setdefault(key, _TitleGroup())
                if direct:
                    pass  # its own slot: never folded into another by title
                elif group.loose:
                    index = group.loose[0]
                elif len(group.direct) == 1:
                    index = group.direct[0]

        if index is None:
            index = len(slots)
            slots.append(item)
            members.append([])
            first_position.append(position)
            if group is not None:
                (group.direct if direct else group.loose).append(index)
        elif item.detail_score > slots[index].detail_score:
            slots[index] = item
        members[index].append(position)
        first_position[index] = min(first_position[index], position)

        slot_by_id.setdefault(item.id, index)
        if canonical:
            canonical_slots[canonical] = index
        if resolved_key:
            resolved_slots[resolved_key] = index

    order = sorted(range(len(slots)), key=first_position.__getitem__)
    return [(slots[i], tuple(listed[p] for p in sorted(members[i]))) for i in order]


def _same_title_variant(first: str, second: str) -> bool:
    """One title is the other plus a trailing code (a whitespace-separated suffix containing a digit)."""
    shorter, longer = sorted((first, second), key=len)
    if not longer.startswith(shorter):
        return False
    suffix = longer[len(shorter):]
    return (not suffix or suffix[0].isspace()) and any(char.isdigit() for char in suffix)
