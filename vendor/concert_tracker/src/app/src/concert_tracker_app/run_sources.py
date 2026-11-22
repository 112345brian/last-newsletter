"""Run every configured source, one failing source never stopping the rest.

For each source: fetch it through the `SourceFetcher` port, record what that came to in the run
history, and judge its health against its earlier runs. The fetcher is the only thing that touches
the network or the ledger; it reports failure by raising `SourceRunError` (or `SourceTimeoutError`),
and everything else it raises is a bug that is allowed to stop the run.

A source that is not in the catalog is refused up front, before any fetch, so a typo never runs a
partial night.
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from concert_tracker_core.source_runs import (
    HISTORY_WINDOW,
    RunStatus,
    SourceHealth,
    SourceOutcome,
    judge_health,
    outcome_status,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from concert_tracker_core.source_runs import SourceCatalog, SourceSpec


class SourceRunError(Exception):
    """The source could not be fetched. Nothing was saved, so running it again is safe."""


class SourceTimeoutError(SourceRunError):
    """The source did not finish in its time; what it saved, if anything, is unknown."""


@dataclass(frozen=True, slots=True)
class FetchTally:
    """What a completed fetch of one source did to the ledger."""

    found: int
    created: int = 0
    mentioned: int = 0


class SourceFetcher(Protocol):
    def fetch(self, spec: SourceSpec) -> FetchTally:
        """Fetch `spec` into the ledger. Raises `SourceRunError` when it could not."""
        ...


class RunHistory(Protocol):
    def recent(self, source: str, limit: int) -> list[SourceOutcome]:
        """The latest outcomes of `source`, newest first."""
        ...

    def record(self, outcome: SourceOutcome) -> None: ...


@dataclass(frozen=True, slots=True)
class SourceResult:
    outcome: SourceOutcome
    health: SourceHealth


@dataclass(frozen=True, slots=True)
class RunReport:
    results: tuple[SourceResult, ...]

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.outcome.errored)

    @property
    def found(self) -> int:
        return sum(r.outcome.found for r in self.results)


class RunSources:
    def __init__(
        self,
        fetcher: SourceFetcher,
        history: RunHistory,
        *,
        now: Callable[[], datetime],
        monotonic: Callable[[], float],
    ) -> None:
        self._fetcher = fetcher
        self._history = history
        self._now = now
        self._monotonic = monotonic

    def execute(self, catalog: SourceCatalog, only: Sequence[str] = ()) -> RunReport:
        """Run the named sources, or every enabled one when none are named."""
        specs = catalog.named(only) if only else catalog.enabled()
        return RunReport(tuple(self._run_one(spec) for spec in specs))

    def _run_one(self, spec: SourceSpec) -> SourceResult:
        started = self._now()
        began = self._monotonic()
        try:
            tally = self._fetcher.fetch(spec)
        except SourceTimeoutError as error:
            outcome = self._failure(spec, RunStatus.TIMED_OUT, started, began, error)
        except SourceRunError as error:
            outcome = self._failure(spec, RunStatus.FAILED, started, began, error)
        else:
            outcome = SourceOutcome(
                source=spec.name,
                status=outcome_status(tally.found),
                started_at=started,
                seconds=self._monotonic() - began,
                found=tally.found,
                created=tally.created,
                mentioned=tally.mentioned,
            )
        earlier = self._history.recent(spec.name, HISTORY_WINDOW)
        self._history.record(outcome)
        return SourceResult(outcome, judge_health(outcome, earlier))

    def _failure(
        self,
        spec: SourceSpec,
        status: RunStatus,
        started: datetime,
        began: float,
        error: Exception,
    ) -> SourceOutcome:
        return SourceOutcome(
            source=spec.name,
            status=status,
            started_at=started,
            seconds=self._monotonic() - began,
            error=str(error) or error.__class__.__name__,
        )
