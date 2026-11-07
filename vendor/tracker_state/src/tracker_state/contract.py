"""Record and action shapes for the tracker contract (docs/tracker-contract.md #2, #4, #5).

An adapter hands a tracker a ``TrackerSpec`` (one ``RecordSpec`` per kind it is willing to
show) and a stream of ``RecordView``s (one per record, display-ready); the tracker never
computes or formats a value, only draws what it is given and calls back with an ``action_id``
and a ``RecordRef``. ``ActivityLookup``/``ActivityStore`` are the activity-log port, typed against
this package's own completed/dismissed rulebook (``tracker_state.user_state_transition``).

A kind is a plain ``str`` the domain owns (a ``StrEnum`` member or ``NewType`` in its own code);
this package defines none and only compares them. An instance serves exactly the kinds of its
specs: zero specs and duplicate kinds fail at construction, as does a section, column or action
naming a kind with no spec, and ``KindGuardedStore`` refuses any ``RecordRef`` whose kind has no
spec, so a wrong write cannot get through even if the spec above it is wrong.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from tracker_state.user_state_transition import Action, Event, Transition, UserState

FieldKind = Literal["text", "number", "date", "url", "badge", "countdown"]
ColumnSlot = Literal["lead", "title", "meta", "side", "detail"]
ActionKind = Literal["primary", "secondary", "destructive"]
ActionOutcome = Literal["changed", "noop", "skipped", "refused", "failed", "queued", "started"]
Scalar = str | int | float
FieldValue = tuple[Scalar, ...]  # ("text", "x") | ("badge", "label", "tone") | ("countdown", 3) ...


class UnknownKind(ValueError):
    """A record, spec part or write names a kind this tracker has no spec for."""


@dataclass(frozen=True)
class RecordRef:
    """Opaque, source-namespaced identity."""
    kind: str
    id: str


@dataclass(frozen=True)
class FieldSpec:
    id: str
    label: str
    type: FieldKind
    sortable: bool = False
    hidden_collapsed: bool = False


@dataclass(frozen=True)
class ColumnSpec:
    slot: ColumnSlot
    field_ids: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    """Which kinds this column applies to; every named kind must have a spec. Empty means any."""


@dataclass(frozen=True)
class SectionSpec:
    id: str
    label: str
    tone: str = "neutral"
    collapsed_by_default: bool = False
    empty_text: str = ""
    state_filter: str | None = None
    kinds: tuple[str, ...] = ()
    """Which RecordSpec kinds may place a record in this section. Empty means any kind the
    tracker instance was given (the common case: one kind, or several kinds sharing a board).
    Every named kind must have a spec."""


@dataclass(frozen=True)
class InputSpec:
    """What ``needs_input`` asks for: free text, or a choice among ``choices``."""
    label: str
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionSpec:
    id: str
    label: str
    icon: str = ""
    kind: ActionKind = "secondary"
    confirm: bool = False
    needs_input: InputSpec | None = None
    long_running: bool = False
    kinds: tuple[str, ...] = ()
    """Which kinds offer this action; every named kind must have a spec. Empty means any."""


@dataclass(frozen=True)
class RecordSpec:
    """Static, once per tracker instance."""
    kind: str
    label_singular: str
    label_plural: str
    fields: tuple[FieldSpec, ...] = ()
    columns: tuple[ColumnSpec, ...] = ()
    sections: tuple[SectionSpec, ...] = ()
    actions: tuple[ActionSpec, ...] = ()


@dataclass(frozen=True)
class TrackerSpec:
    """Passed to ``create_app``: everything one tracker instance is willing to show.

    An instance serves exactly the kinds of its specs (one ``RecordSpec`` per kind; an admin board
    shows both "submission" and "event"). There is no second list of kinds to drift from the specs:
    zero specs, duplicate kinds, and a section, column or action naming a kind with no spec all fail
    here. A single-kind instance is one spec; a caller that wants that as a hard rule asserts
    ``len(spec.kinds) == 1``.
    """
    specs: tuple[RecordSpec, ...]

    def __post_init__(self) -> None:
        if not self.specs:
            raise ValueError("a TrackerSpec needs at least one RecordSpec")
        kinds = [spec.kind for spec in self.specs]
        if len(set(kinds)) != len(kinds):
            raise ValueError(f"duplicate RecordSpec.kind in specs: {kinds}")
        for spec in self.specs:
            for part in (*spec.columns, *spec.sections, *spec.actions):
                missing = [k for k in part.kinds if k not in kinds]
                if missing:
                    raise UnknownKind(
                        f"{type(part).__name__} in RecordSpec({spec.kind!r}) names {missing}, which has no RecordSpec")

    @property
    def kinds(self) -> frozenset[str]:
        return frozenset(spec.kind for spec in self.specs)

    def spec_for(self, kind: str) -> RecordSpec:
        for spec in self.specs:
            if spec.kind == kind:
                return spec
        raise UnknownKind(f"{kind!r} has no RecordSpec (serves: {sorted(self.kinds)})")

    def accepts(self, ref: RecordRef) -> bool:
        return ref.kind in self.kinds

    def require(self, ref: RecordRef) -> RecordRef:
        self.spec_for(ref.kind)
        return ref

    def check_view(self, view: RecordView) -> RecordView:
        """A view must be of a served kind and sit in a section its kind's spec declares."""
        spec = self.spec_for(view.ref.kind)
        if view.section not in {sec.id for sec in spec.sections}:
            raise ValueError(f"view {view.ref} is in unknown section {view.section!r}")
        return view


@dataclass
class RecordView:
    """One record, finished and display-ready: the tracker draws this, it computes nothing."""
    ref: RecordRef
    title: str
    fields: Mapping[str, FieldValue]
    section: str
    sort_key: tuple[Scalar, ...]
    state: UserState | None
    actions: list[str]
    detail: Mapping[str, FieldValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionResult:
    """Never a bare truthy/falsy: callers must tell changed from no-op from refused."""
    outcome: ActionOutcome
    reason: str | None = None
    message: str | None = None
    view: RecordView | None = None
    job_id: str | None = None


class ActivityLookup(Protocol):
    """Loaded once per request; the tracker asks this, never a record dict's own fields."""
    def is_completed(self, ref: RecordRef) -> bool: ...
    def is_dismissed(self, ref: RecordRef) -> bool: ...
    def ever_completed(self, ref: RecordRef) -> bool: ...


class ActivityStore(Protocol):
    """Tracker-facing port; implemented per backend by the adapter (docs/tracker-contract.md #5)."""
    def snapshot(self) -> ActivityLookup: ...
    def apply(self, action: Action, ref: RecordRef, *, actor: str) -> Transition: ...
    def history(self, ref: RecordRef) -> Sequence[Event]: ...


class _GuardedLookup:
    def __init__(self, inner: ActivityLookup, spec: TrackerSpec) -> None:
        self._inner, self._spec = inner, spec

    def is_completed(self, ref: RecordRef) -> bool:
        return self._inner.is_completed(self._spec.require(ref))

    def is_dismissed(self, ref: RecordRef) -> bool:
        return self._inner.is_dismissed(self._spec.require(ref))

    def ever_completed(self, ref: RecordRef) -> bool:
        return self._inner.ever_completed(self._spec.require(ref))


class KindGuardedStore:
    """Wrap any ``ActivityStore``: a ``RecordRef`` whose kind has no spec raises ``UnknownKind``
    before it reaches the backend."""

    def __init__(self, inner: ActivityStore, spec: TrackerSpec) -> None:
        self._inner, self._spec = inner, spec

    def snapshot(self) -> ActivityLookup:
        return _GuardedLookup(self._inner.snapshot(), self._spec)

    def apply(self, action: Action, ref: RecordRef, *, actor: str) -> Transition:
        return self._inner.apply(action, self._spec.require(ref), actor=actor)

    def history(self, ref: RecordRef) -> Sequence[Event]:
        return self._inner.history(self._spec.require(ref))
