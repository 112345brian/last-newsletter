"""Application rule: give the open events already in the ledger the artists their titles name.

The same rule ingestion applies to new events (`entities_with_title_artists`), run over what is
stored. An event whose source supplied a headliner or support is left alone; one the parser cannot
read is left alone; owner-origin entities are carried over untouched. It is idempotent: a second
run finds every event it filled already has an artist and changes nothing.

`plan` only reads; `apply` writes through `EventRepository.upsert`, which keeps mentions, owner
state and `last_seen` as they are. The caller decides where `apply` runs (a dry run applies to a
throwaway copy of the ledger).
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from concert_tracker_core.title_artists import entities_with_title_artists, has_artist

if TYPE_CHECKING:
    from concert_tracker_core.event_ports import EventRepository
    from concert_tracker_core.events import EntityRef, Event
    from concert_tracker_core.promoters import PromoterDirectory


@dataclass(frozen=True, slots=True)
class EventArtistsAdded:
    """One event and the entities the backfill would add to it."""

    event: Event
    added: tuple[EntityRef, ...]


@dataclass(frozen=True, slots=True)
class BackfillPlan:
    """What a backfill would do: counts over every open event, plus each change."""

    scanned: int
    had_artists: int
    changes: tuple[EventArtistsAdded, ...]

    @property
    def unread(self) -> int:
        """Events with no artist from the source whose title the parser added nothing for."""
        return self.scanned - self.had_artists - len(self.changes)


class BackfillTitleArtists:
    def __init__(self, repository: EventRepository, promoters: PromoterDirectory) -> None:
        self._repository = repository
        self._promoters = promoters

    def plan(self) -> BackfillPlan:
        events = self._repository.list_open()
        had = 0
        changes: list[EventArtistsAdded] = []
        for event in events:
            if has_artist(event.entities):
                had += 1
                continue
            entities = entities_with_title_artists(event.title, event.entities, self._promoters)
            if entities != event.entities:
                changes.append(EventArtistsAdded(event, entities[len(event.entities) :]))
        return BackfillPlan(scanned=len(events), had_artists=had, changes=tuple(changes))

    def apply(self, plan: BackfillPlan) -> int:
        """Write the plan's changes; returns how many events were updated."""
        for change in plan.changes:
            event = change.event
            self._repository.upsert(replace(event, entities=(*event.entities, *change.added)))
        return len(plan.changes)
