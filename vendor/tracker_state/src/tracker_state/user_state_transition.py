"""The one definition of what completed / dismissed mean for a record.

"Completed" is the neutral word for the positive outcome (a job applied to, a
submission approved, a task done). A domain whose stored rows use other words
translates at its store edge; this module speaks only the neutral vocabulary.

Two *stores* (for example hosted rows and local files) hold the
same row. Neither decides a rule: both load the current row, call
:func:`apply_action`, and persist what it returns. A backend that wants a
different answer has to change this file, where the equivalence harness
(``tests/test_activity_backend_equivalence.py``) will see it.

The row
-------
``status``      ``active`` | ``completed`` | ``dismissed`` (``archived`` is written
                by nothing here and left alone by uncomplete / undismiss)
``completed_at``ISO date; survives a later dismissal (the completion happened)
``dismissed_at``ISO timestamp; set only while dismissed
``note``        the dismiss reason; set only while dismissed

Completed and dismissed are exclusive: ``is_completed`` is ``status == "completed"``
and ``is_dismissed`` is ``status == "dismissed"``. Analytics that mean "was ever
completed" ask :func:`ever_completed` (``completed_at`` is set), so dismissing a
completed record does not make it vanish from a count.

What a transition returns
-------------------------
``delta`` holds ONLY the columns that change. A PostgREST merge-duplicates write
sends exactly the keys it is given, so a full row would overwrite columns the
action never meant to touch. ``changed`` is ``bool(delta)`` -- one truthful
no-op signal for every backend. ``events`` are audit rows as data (the store
decides whether it has anywhere to write them); a no-op emits none.

Timestamps are opaque ISO strings supplied by the caller (``now``), so this
module is deterministic and free of clocks, I/O and imports beyond the
standard library.

One deliberate narrowness: "no-op" here is about *state*. A store that also
keeps display fields (title, org) beside the row may still report a change when
only those differ; that is the store's call, not a rule about completed/dismissed.
"""
from __future__ import annotations

__arbor__ = {"ring": "core"}

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

ACTIVE = "active"
COMPLETED = "completed"
DISMISSED = "dismissed"
ARCHIVED = "archived"

# skipped_reason values (neutral; a domain maps them to its own stored strings at its store edge).
ALREADY_COMPLETED_UNCHANGED = "already_completed_unchanged"
NOT_COMPLETED = "not_completed"
ALREADY_DISMISSED = "already_dismissed"
NOT_DISMISSED = "not_dismissed"
TERMINAL = "terminal"


@dataclass(frozen=True)
class UserState:
    status: str = ACTIVE
    completed_at: str | None = None
    dismissed_at: str | None = None
    note: str | None = None
    # Set only by a Dismiss(terminal=True) (e.g. a rejected moderation item); locks
    # out Complete/Undismiss. In-memory only -- NOT one of ``columns()``'s keys,
    # so neither real store (hosted ``job_user_state``, JSON) persists or round-trips
    # it; it only survives within one chain of ``apply_action`` calls. No caller sets
    # it today, so this is additive and changes no existing backend's wire shape.
    terminal: bool = False

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | None) -> UserState:
        """Build from a hosted row or a JSON record; missing keys are defaults."""
        if not row:
            return cls()
        return cls(
            status=str(row.get("status") or ACTIVE),
            completed_at=row.get("completed_at") or None,
            dismissed_at=row.get("dismissed_at") or None,
            note=row.get("note") or None,
        )

    def columns(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "completed_at": self.completed_at,
            "dismissed_at": self.dismissed_at,
            "note": self.note,
        }


@dataclass(frozen=True)
class Complete:
    completed_on: str
    # Opaque to this module: carried verbatim into the audit event's payload
    # (never into the row -- the row does not store them). A domain puts
    # whatever fields it wants here (jobs: title/org); the contract fixes no
    # keys, so a non-job domain has somewhere neutral to put its own.
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Uncomplete:
    pass


@dataclass(frozen=True)
class Dismiss:
    reason: str = ""
    # True for a terminal rejection (city-events: reject a pending submission).
    # Only takes effect on the transition INTO dismissed; repeating a Dismiss
    # on an already-dismissed record never changes ``terminal`` (moderation
    # rejects once; it does not escalate a prior plain dismissal later).
    terminal: bool = False


@dataclass(frozen=True)
class Undismiss:
    pass


Action = Complete | Uncomplete | Dismiss | Undismiss


@dataclass(frozen=True)
class Event:
    event_type: str  # completed | uncompleted | dismissed | undismissed
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Transition:
    before: UserState
    after: UserState
    delta: Mapping[str, Any]
    events: tuple[Event, ...]
    skipped_reason: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.delta)


def is_completed(state: UserState) -> bool:
    return state.status == COMPLETED


def is_dismissed(state: UserState) -> bool:
    return state.status == DISMISSED


def ever_completed(state: UserState) -> bool:
    """True once a completion was recorded, even if the record was dismissed since."""
    return state.completed_at is not None


def _noop(state: UserState, reason: str) -> Transition:
    return Transition(before=state, after=state, delta={}, events=(), skipped_reason=reason)


def _moved(state: UserState, target: UserState, events: tuple[Event, ...], noop_reason: str) -> Transition:
    delta = {col: val for col, val in target.columns().items() if val != state.columns()[col]}
    if not delta:
        return _noop(state, noop_reason)
    return Transition(before=state, after=target, delta=delta, events=events)


def apply_action(state: UserState | None, action: Action, *, now: str) -> Transition:
    """The transition for ``action`` on ``state`` (``None`` means no row yet)."""
    state = state or UserState()

    if isinstance(action, Complete):
        if state.terminal:
            return _noop(state, TERMINAL)
        target = UserState(status=COMPLETED, completed_at=action.completed_on, dismissed_at=None, note=None)
        event = Event("completed", dict(action.detail))
        return _moved(state, target, (event,), ALREADY_COMPLETED_UNCHANGED)

    if isinstance(action, Uncomplete):
        # Archived rows are outside the completed/dismissed lifecycle. Preserve
        # the entire row even if legacy data happens to retain completed_at.
        if state.status == ARCHIVED:
            return _noop(state, NOT_COMPLETED)
        if state.status == COMPLETED:
            target = replace(state, status=ACTIVE, completed_at=None)
        elif state.completed_at is not None:
            # Dismissed (or otherwise not "completed") but a completion is on
            # record: forget the completion, do NOT touch the dismissal.
            target = replace(state, completed_at=None)
        else:
            return _noop(state, NOT_COMPLETED)
        return _moved(state, target, (Event("uncompleted"),), NOT_COMPLETED)

    if isinstance(action, Dismiss):
        reason = (action.reason or "").strip()
        note = reason or None
        payload = {"reason": reason} if reason else {}
        if state.status == DISMISSED:
            # Re-dismissing keeps the ORIGINAL dismissed_at; only a changed
            # reason is news. ``terminal`` is set only by the transition INTO
            # dismissed (below), never escalated by a repeat dismiss.
            target = replace(state, note=note)
        else:
            target = replace(state, status=DISMISSED, dismissed_at=now, note=note, terminal=action.terminal)
        return _moved(state, target, (Event("dismissed", payload),), ALREADY_DISMISSED)

    if isinstance(action, Undismiss):
        if state.status != DISMISSED:
            return _noop(state, NOT_DISMISSED)
        if state.terminal:
            return _noop(state, TERMINAL)
        restored = COMPLETED if state.completed_at is not None else ACTIVE
        target = replace(state, status=restored, dismissed_at=None, note=None)
        return _moved(state, target, (Event("undismissed"),), NOT_DISMISSED)

    raise TypeError(f"unknown action {action!r}")
