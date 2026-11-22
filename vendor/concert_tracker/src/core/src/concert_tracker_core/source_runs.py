"""Running many event sources: what a source is, what a run of it came to, and whether it is well.

Pure rules, no I/O. A `SourceSpec` names one configured source (an iCal feed, a venue site) and the
options its fetch takes. A `SourceOutcome` is what one run of it came to; `EMPTY` (it ran fine and
found nothing) is its own state, never folded into success, because a venue whose page changed
shape usually looks exactly like that. `judge_health` compares a fresh outcome with the source's
recent history, so a source that fails repeatedly, or suddenly finds far less than it used to,
is said to be unwell instead of staying quietly "ok".
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass, field
from enum import StrEnum
from statistics import median
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

DEFAULT_TIMEOUT_S = 120
MAX_TIMEOUT_S = 3600
FAILURES_BEFORE_FAILING = 3
BASELINE_MIN_SAMPLES = 5
BASELINE_MIN_FOUND = 5
VOLUME_DROP_FRACTION = 0.35
HISTORY_WINDOW = 14


def source_key(name: str) -> str:
    """How source names are compared everywhere: ignoring case and surrounding space."""
    return name.strip().casefold()


class SourceCatalogError(ValueError):
    """The source catalog is malformed: names the entry and what is wrong."""


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """One configured source: `name` (also its label on every event it lists), the adapter
    `kind` and the `options` that adapter's fetch takes (for example `feed_url`)."""

    name: str
    kind: str
    options: tuple[tuple[str, str], ...] = ()
    timeout_s: int = DEFAULT_TIMEOUT_S
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip() or "\x00" in self.name:
            msg = f"source name {self.name!r} must be non-blank text without padding"
            raise SourceCatalogError(msg)
        if not self.kind.strip():
            msg = f"source {self.name!r}: kind must not be blank"
            raise SourceCatalogError(msg)
        if not 1 <= self.timeout_s <= MAX_TIMEOUT_S:
            msg = f"source {self.name!r}: timeout_s must be between 1 and {MAX_TIMEOUT_S}"
            raise SourceCatalogError(msg)

    def option_map(self) -> dict[str, str]:
        return dict(self.options)


@dataclass(frozen=True, slots=True)
class SourceCatalog:
    """The sources to run, by name (compared the way names are everywhere: case-insensitively)."""

    specs: tuple[SourceSpec, ...] = ()

    @classmethod
    def of(cls, specs: Iterable[SourceSpec]) -> SourceCatalog:
        seen: dict[str, SourceSpec] = {}
        for spec in specs:
            key = source_key(spec.name)
            if key in seen:
                msg = f"source {spec.name!r} is listed twice"
                raise SourceCatalogError(msg)
            seen[key] = spec
        return cls(tuple(seen.values()))

    def with_overrides(self, other: SourceCatalog) -> SourceCatalog:
        """This catalog with `other`'s entries replacing same-named ones and adding new ones."""
        merged = {source_key(s.name): s for s in self.specs}
        merged.update({source_key(s.name): s for s in other.specs})
        return SourceCatalog(tuple(merged.values()))

    def named(self, names: Iterable[str]) -> list[SourceSpec]:
        """The specs called `names`, in catalog order. An unknown name is an error, not a skip."""
        wanted = {source_key(n): n for n in names}
        known = {source_key(s.name) for s in self.specs}
        missing = [original for key, original in wanted.items() if key not in known]
        if missing:
            msg = f"unknown source {', '.join(missing)}"
            raise SourceCatalogError(msg)
        return [s for s in self.specs if source_key(s.name) in wanted]

    def enabled(self) -> list[SourceSpec]:
        return [s for s in self.specs if s.enabled]


def _text(value: object, what: str) -> str:
    if not isinstance(value, str):
        msg = f"{what} must be text"
        raise SourceCatalogError(msg)
    return value


def _spec_from(entry: object) -> SourceSpec:
    if not isinstance(entry, dict):
        msg = "each source must be an object"
        raise SourceCatalogError(msg)
    name = _text(entry.get("name", ""), "name")
    options_raw = entry.get("options", {})
    if not isinstance(options_raw, dict):
        msg = f"source {name!r}: options must be an object of text values"
        raise SourceCatalogError(msg)
    options = tuple(
        (_text(k, "option name"), _text(v, f"option {k!r}")) for k, v in options_raw.items()
    )
    timeout = entry.get("timeout_s", DEFAULT_TIMEOUT_S)
    enabled = entry.get("enabled", True)
    if isinstance(timeout, bool) or not isinstance(timeout, int):
        msg = f"source {name!r}: timeout_s must be a whole number"
        raise SourceCatalogError(msg)
    if not isinstance(enabled, bool):
        msg = f"source {name!r}: enabled must be true or false"
        raise SourceCatalogError(msg)
    return SourceSpec(
        name=name,
        kind=_text(entry.get("kind", ""), "kind"),
        options=options,
        timeout_s=timeout,
        enabled=enabled,
    )


def parse_source_catalog(data: object) -> SourceCatalog:
    """`{"sources": [{"name": ..., "kind": ..., "options": {...}, "timeout_s": 120}]}`."""
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        msg = 'expected an object with a "sources" list'
        raise SourceCatalogError(msg)
    return SourceCatalog.of(_spec_from(entry) for entry in data["sources"])


class RunStatus(StrEnum):
    OK = "ok"  # ran, and found events
    EMPTY = "empty"  # ran without error and found none
    FAILED = "failed"  # the source or its site errored; nothing was saved
    TIMED_OUT = "timed_out"  # gave up waiting; nothing is known about what it saved


@dataclass(frozen=True, slots=True)
class SourceOutcome:
    """What one run of one source came to."""

    source: str
    status: RunStatus
    started_at: datetime
    seconds: float = 0.0
    found: int = 0
    created: int = 0
    mentioned: int = 0
    error: str = ""

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None:
            msg = "started_at must be timezone-aware"
            raise ValueError(msg)
        if min(self.found, self.created, self.mentioned) < 0 or self.seconds < 0:
            msg = "counts and seconds must not be negative"
            raise ValueError(msg)

    @property
    def errored(self) -> bool:
        return self.status in (RunStatus.FAILED, RunStatus.TIMED_OUT)


class HealthLevel(StrEnum):
    NEW = "new"  # no earlier run to compare with
    HEALTHY = "healthy"
    DEGRADED = "degraded"  # worth a look: failed once or twice, or found far less than usual
    FAILING = "failing"  # failed several runs in a row


@dataclass(frozen=True, slots=True)
class SourceHealth:
    level: HealthLevel
    reasons: tuple[str, ...] = field(default=())


def judge_health(latest: SourceOutcome, earlier: Sequence[SourceOutcome]) -> SourceHealth:
    """How well `latest` says the source is, given its `earlier` outcomes (newest first).

    Failure streaks count `latest` too. A volume drop needs a baseline: at least
    `BASELINE_MIN_SAMPLES` earlier runs that completed, with a median of at least
    `BASELINE_MIN_FOUND`, so a source that is always small never trips it.
    """
    window = earlier[:HISTORY_WINDOW]
    streak = 0
    for outcome in (latest, *window):
        if not outcome.errored:
            break
        streak += 1
    if streak >= FAILURES_BEFORE_FAILING:
        return SourceHealth(HealthLevel.FAILING, (f"failed {streak} runs in a row",))
    if latest.errored:
        return SourceHealth(HealthLevel.DEGRADED, (f"last run {latest.status.value}",))
    done = [o.found for o in window if not o.errored]
    if len(done) < BASELINE_MIN_SAMPLES:
        level = HealthLevel.HEALTHY if window else HealthLevel.NEW
        return SourceHealth(level)
    baseline = median(done)
    if baseline >= BASELINE_MIN_FOUND and latest.found < baseline * VOLUME_DROP_FRACTION:
        what = "found nothing" if latest.found == 0 else f"found only {latest.found}"
        return SourceHealth(
            HealthLevel.DEGRADED,
            (f"{what}, far below the usual ~{baseline:g} (its page may have changed)",),
        )
    return SourceHealth(HealthLevel.HEALTHY)


def outcome_status(found: int) -> RunStatus:
    """A fetch that completed: OK when it found events, EMPTY when it found none."""
    return RunStatus.OK if found > 0 else RunStatus.EMPTY


def option_mapping(options: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(options.items())
