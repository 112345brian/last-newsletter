"""Port contract: runs against the semantic index and the difflib stand-in."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from semantic_support import Ev, SimilarIndex

if TYPE_CHECKING:
    from collections.abc import Callable

D = date(2026, 12, 12)
HOSTILE = ["", "   ", "\x00", "a\x00b" * 50, "x" * 200_000, "\ud800", "🎶" * 5000, "\n\t"]


def test_finds_paraphrase_and_excludes_self(make_index: Callable[[], SimilarIndex]) -> None:
    idx = make_index()
    idx.index(Ev("1", "Jon Hopkins live at Brooklyn Steel", "Brooklyn Steel", day=D))
    idx.index(Ev("2", "Annual Book Fair", "Union Square", day=D))
    hits = idx.similar(Ev("3", "Jon Hopkins: Live at Brooklyn Steel", "Brooklyn Steel", day=D))
    assert hits[0][0] == "1"
    assert all(i != "2" for i, _ in hits)
    assert idx.similar(Ev("1", "Jon Hopkins live at Brooklyn Steel", "Brooklyn Steel", day=D)) == []


def test_scores_in_unit_interval_sorted_and_limited(make_index: Callable[[], SimilarIndex]) -> None:
    idx = make_index()
    for n in range(10):
        idx.index(Ev(str(n), f"Jon Hopkins live show {n}", "Steel", day=D))
    hits = idx.similar(Ev("q", "Jon Hopkins live show", "Steel", day=D), limit=3)
    assert len(hits) <= 3
    assert all(0.0 <= s <= 1.0 for _, s in hits)
    assert [s for _, s in hits] == sorted((s for _, s in hits), reverse=True)
    assert idx.similar(Ev("q", "Jon Hopkins live show"), limit=0) == []


def test_deterministic(make_index: Callable[[], SimilarIndex]) -> None:
    idx = make_index()
    for n in range(5):
        idx.index(Ev(str(n), "Same Title", "Same Venue", day=D))
    q = Ev("q", "Same Title", "Same Venue", day=D)
    assert idx.similar(q) == idx.similar(q)


@pytest.mark.parametrize("text", HOSTILE)
def test_never_raises_on_hostile_text(make_index: Callable[[], SimilarIndex], text: str) -> None:
    idx = make_index()
    idx.index(Ev("1", "Normal Event", "Venue", day=D))
    idx.index(Ev("2", text, text, (text,), (text,), D))
    hits = idx.similar(Ev("3", text, text, (text,), (text,), None))
    assert all(0.0 <= s <= 1.0 for _, s in hits)


def test_reindex_replaces(make_index: Callable[[], SimilarIndex]) -> None:
    idx = make_index()
    idx.index(Ev("1", "Alpha Fest", day=D))
    idx.index(Ev("1", "Totally Different Gathering", day=D))
    assert idx.similar(Ev("q", "Alpha Fest", day=D)) == []
