"""Adapts the local semantic index (`adapter_semantic`) to core's `SimilarEventIndex` port.

Two jobs live here because only the composition root may know both sides:

* translate core's `Event` / `EventDraft` into the plain shape the index reads, and
* keep the index in step with the ledger (the ledger is the source of truth, the index is a
  derived cache that can always be rebuilt from it).
"""

from __future__ import annotations

__arbor__ = {"ring": "cli"}

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from last_newsletter_adapter_semantic import DEFAULT_THRESHOLD
from last_newsletter_core.event_identity import IdentityPolicy
from last_newsletter_core.events import EntityRole, EventId, local_date

if TYPE_CHECKING:
    from datetime import date

    from last_newsletter_adapter_semantic import HashedNgramIndex
    from last_newsletter_core.events import Event, EventDraft

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
        hits = self._index.similar(_view("", candidate), limit=limit)
        return [(EventId(UUID(ident)), score) for ident, score in hits]


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
