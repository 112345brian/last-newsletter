"""Adapts the local semantic index (`ngram_index`) to core's `SimilarEventIndex` port.

Two jobs live here because only the composition root may know both sides:

* translate core's `Event` / `EventDraft` into the plain shape the index reads, and
* keep the index in step with the ledger (the ledger is the source of truth, the index is a
  derived cache that can always be rebuilt from it).
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from concert_tracker_core.event_identity import IdentityPolicy
from concert_tracker_core.events import EntityRole, EventId, local_date
from concert_tracker_ngram_index import DEFAULT_THRESHOLD

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from concert_tracker_core.event_ports import SimilarEventIndex
    from concert_tracker_core.events import Event, EventDraft
    from concert_tracker_ngram_index import HashedNgramIndex

# A similarity score alone must never merge two events: it only ever proposes a link for the
# owner to review. `merge_at` above 1.0 can never be reached; `link_at` is the index threshold.
LINK_ONLY_POLICY = IdentityPolicy(merge_at=math.inf, link_at=DEFAULT_THRESHOLD)


@dataclass(frozen=True, slots=True)
class _Indexable:
    id: str
    title: str
    venue: str
    entities: tuple[str, ...]
    tags: tuple[str, ...]
    day: date | None


def _view(ident: str, item: Event | EventDraft) -> _Indexable:
    venue = next((e.name for e in item.entities if e.role is EntityRole.VENUE), "")
    return _Indexable(
        id=ident,
        title=item.title,
        venue=venue,
        entities=tuple(e.name for e in item.entities if e.role is not EntityRole.VENUE),
        tags=tuple(sorted(item.tags)),
        day=local_date(item.when),
    )


class CoreSimilarIndex:
    """`SimilarEventIndex` for core, backed by `HashedNgramIndex`."""

    def __init__(self, index: HashedNgramIndex) -> None:
        self._index = index

    def index(self, event: Event) -> None:
        self._index.index(_view(str(event.id), event))

    def similar(self, candidate: EventDraft, *, limit: int) -> list[tuple[EventId, float]]:
        """Hits on the same date score as the index says; hits on another date (the same series
        a week later) are found by asking again with the date left out, which the index scores
        as "date unknown". Core links them but never merges across dates."""
        view = _view("", candidate)
        best: dict[str, float] = {}
        for query in (view, replace(view, day=None)):
            for ident, score in self._index.similar(query, limit=limit):
                best[ident] = max(score, best.get(ident, 0.0))
        ranked = sorted(best.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
        return [(EventId(UUID(ident)), score) for ident, score in ranked]


def sync_index(index: HashedNgramIndex, events: list[Event]) -> bool:
    """Make the index cover exactly `events`. Returns True when it had to rebuild.

    A missing index file, a half-written one, or one that disagrees with the ledger about
    which events exist is rebuilt from the ledger, so the first run after an upgrade (or after
    deleting the index) just works.
    """
    wanted = {str(e.id) for e in events}
    if index.ids() == wanted:
        return False
    index.clear()
    adapter = CoreSimilarIndex(index)
    for event in events:
        adapter.index(event)
    return True


class SimilarBackend(Protocol):
    """An optional extra similarity index, such as the embedding one in `adapter_embeddings`.

    It answers core's two `SimilarEventIndex` questions and also looks after its own cache
    (`sync`, `close`). `problems` collects anything that stopped it working, in plain words, so
    the run summary can say so; it must never raise out of the other methods, because an optional
    helper must not be able to break a run.
    """

    problems: list[str]

    def index(self, event: Event) -> None: ...

    def similar(self, candidate: EventDraft, *, limit: int) -> list[tuple[EventId, float]]: ...

    def sync(self, events: Sequence[Event]) -> bool: ...

    def close(self) -> None: ...


class CombinedSimilarIndex:
    """Several similarity indexes behind core's one port: an event is a possible duplicate if any
    index says so, and keeps the best score any of them gave it.

    Every index must score on the same scale (core compares the result to one link threshold), so
    each backend rescales its own measure before it gets here.
    """

    def __init__(self, indexes: Sequence[SimilarEventIndex]) -> None:
        self._indexes = tuple(indexes)

    def index(self, event: Event) -> None:
        for index in self._indexes:
            index.index(event)

    def similar(self, candidate: EventDraft, *, limit: int) -> list[tuple[EventId, float]]:
        best: dict[EventId, float] = {}
        for index in self._indexes:
            for event_id, score in index.similar(candidate, limit=limit):
                best[event_id] = max(score, best.get(event_id, 0.0))
        ranked = sorted(best.items(), key=lambda pair: (-pair[1], str(pair[0])))
        return ranked[:limit]
