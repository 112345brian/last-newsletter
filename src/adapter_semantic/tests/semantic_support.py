"""Shared test doubles for the semantic index suites."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date


class SimilarIndex(Protocol):
    def index(self, event: Ev) -> None: ...
    def similar(self, candidate: Ev, *, limit: int = 5) -> list[tuple[str, float]]: ...


@dataclass(frozen=True)
class Ev:
    id: str
    title: str
    venue: str = ""
    entities: Sequence[str] = field(default_factory=tuple)
    tags: Sequence[str] = field(default_factory=tuple)
    day: date | None = None


class DifflibIndex:
    """Stand-in for core's stdlib difflib default (core's port has not landed yet)."""

    def __init__(self) -> None:
        self._rows: dict[str, str] = {}

    def index(self, event: Ev) -> None:
        self._rows[str(event.id)] = f"{event.title} {event.venue}".casefold()

    def similar(self, candidate: Ev, *, limit: int = 5) -> list[tuple[str, float]]:
        text = f"{candidate.title} {candidate.venue}".casefold()
        hits = [
            (i, round(difflib.SequenceMatcher(None, text, t).ratio(), 6))
            for i, t in self._rows.items()
            if i != str(candidate.id)
        ]
        return sorted(((i, s) for i, s in hits if s >= 0.5), key=lambda p: (-p[1], p[0]))[
            : max(limit, 0)
        ]
