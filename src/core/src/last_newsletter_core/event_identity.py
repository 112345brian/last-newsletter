"""The identity ladder (docs/design/event-ledger.md section 5): is this draft an event we
already know, or a new one?

Rungs, stopping at the first hit:

1. `uid`: the iCalendar UID.
2. canonical URL (must have a path; a bare homepage identifies nothing) and a date within one
   day, since a venue reuses one page for a whole series.
3. normalized title + venue, on the same local date. One day off counts only when a listed date
   is uncertain (an after-midnight listing, `night_of`): a title listed on two consecutive days
   is two events, never one cited twice.
4. optional: a `SimilarEventIndex` score, consulted only if rungs 1 to 3 found nothing.

Failure policy: when a draft could be several existing events, or a rung found something
suspicious but not certain, it stays a NEW event and is linked to those events as a possible
duplicate. Showing a duplicate is safe; hiding a live item is not.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from last_newsletter_core.event_rules import normalize_text
from last_newsletter_core.events import EventId, MatchRule, local_date

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from last_newsletter_core.events import Event, EventDraft

_URL_WITH_PATH = re.compile(r"^https?://[^/?]+/.+")
_WINDOW_DAYS = 1


@dataclass(frozen=True, slots=True)
class IdentityPolicy:
    """Thresholds for the optional similarity rung (scores are in [0, 1])."""

    merge_at: float = 0.92
    link_at: float = 0.75


@dataclass(frozen=True, slots=True)
class Decision:
    """`event` is the existing event the draft was matched to (via `rule`), or None for a new
    event, in which case `possible_duplicates` lists the events to link it to (sorted)."""

    rule: MatchRule
    event: Event | None = None
    possible_duplicates: tuple[EventId, ...] = ()


def _days_apart(draft: EventDraft, event: Event) -> int:
    return abs((local_date(event.when) - local_date(draft.when)).days)


def _same_day(draft: EventDraft, event: Event) -> bool:
    """Same listed date, or one day off when either side's date is uncertain (after midnight)."""
    apart = _days_apart(draft, event)
    if apart == 0:
        return True
    return apart <= _WINDOW_DAYS and (draft.night_of is not None or event.night_of is not None)


def _closest(draft: EventDraft, events: Sequence[Event]) -> list[Event]:
    """Events on the draft's own date if any, else those one day off."""
    exact = [e for e in events if _days_apart(draft, e) == 0]
    return exact or list(events)


def _linked(events: Sequence[Event]) -> tuple[EventId, ...]:
    return tuple(sorted({e.id for e in events}, key=str))


def _venues_conflict(draft: EventDraft, event: Event) -> bool:
    a, b = normalize_text(draft.venue), normalize_text(event.venue)
    return bool(a and b and a != b)


def _is_dated_sibling(draft: EventDraft, event: Event) -> bool:
    """Same title and venue, different listed date: separate by design, so not a duplicate."""
    return (
        normalize_text(event.title) == normalize_text(draft.title)
        and normalize_text(event.venue) == normalize_text(draft.venue)
        and not _same_day(draft, event)
    )


def _decide(rule: MatchRule, found: Sequence[Event], soft: dict[EventId, Event]) -> Decision:
    """One hit is a match; several are ambiguous, so keep separate and link them all."""
    if len(found) == 1:
        return Decision(rule, found[0])
    return Decision(MatchRule.NEW, None, _linked([*found, *soft.values()]))


def identify(
    draft: EventDraft,
    pool: Sequence[Event],
    *,
    similar: Callable[[], Sequence[tuple[Event, float]]] | None = None,
    policy: IdentityPolicy | None = None,
) -> Decision:
    """Match `draft` against `pool` (open or recently closed events). Pure."""
    policy = policy or IdentityPolicy()
    soft: dict[EventId, Event] = {}  # suspicious but not certain: link, never merge

    if draft.uid is not None:
        by_uid = [e for e in pool if e.uid == draft.uid]
        if by_uid:
            return _decide(MatchRule.UID, by_uid, {})

    if draft.url is not None and _URL_WITH_PATH.match(draft.url):
        same_url = [e for e in pool if e.url == draft.url]
        near = [e for e in same_url if _days_apart(draft, e) <= _WINDOW_DAYS]
        if near:
            return _decide(MatchRule.URL, near, {})
        soft.update({e.id: e for e in same_url})

    title = normalize_text(draft.title)
    venue = normalize_text(draft.venue)
    same_title = [e for e in pool if normalize_text(e.title) == title and _same_day(draft, e)]
    same_venue = [e for e in same_title if normalize_text(e.venue) == venue]
    if same_venue:
        return _decide(MatchRule.TITLE_DATE_VENUE, _closest(draft, same_venue), soft)
    soft.update({e.id: e for e in same_title if not _venues_conflict(draft, e)})

    if similar is not None:
        # Any date may be linked (the index already discounts a date mismatch), but an event
        # with the very same title and venue on another date is a known-separate sibling.
        hits = [
            (e, score)
            for e, score in similar()
            if score >= policy.link_at and not _is_dated_sibling(draft, e)
        ]
        mergeable = [
            e
            for e, score in hits
            if score >= policy.merge_at and _same_day(draft, e) and not _venues_conflict(draft, e)
        ]
        if mergeable:
            return _decide(MatchRule.SIMILAR, mergeable, soft)
        soft.update({e.id: e for e, _ in hits})

    return Decision(MatchRule.NEW, None, _linked(list(soft.values())))
