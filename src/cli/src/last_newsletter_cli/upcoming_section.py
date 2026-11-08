"""The "Coming up" input of `build`: read the event ledger (read-only) and say what happened.

A digest never fails because of the ledger. A missing file just means `process` has not run; a
locked, corrupt or out-of-date ledger is reported once on stderr and the digest is built without
the section. Nothing here writes to the ledger, creates a file, or migrates a schema.
"""

from __future__ import annotations

__arbor__ = {"ring": "cli"}

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from last_newsletter_adapter_ledger import (
    SchemaTooNewError,
    SchemaTooOldError,
    SqliteEventRepository,
)
from last_newsletter_core.use_cases.list_upcoming_events import ListUpcomingEventsUseCase

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from last_newsletter_core.use_cases.list_upcoming_events import UpcomingEvents

LOCK_WAIT_S = 3.0  # a digest must not hang behind a long `process` run

_STALE_HINT = "run `process` once to upgrade it"


@dataclass(frozen=True, slots=True)
class UpcomingOutcome:
    """The section (None when omitted), the one stdout line, and at most one warning."""

    upcoming: UpcomingEvents | None
    line: str
    warning: str | None = None


def describe_included(upcoming: UpcomingEvents) -> str:
    count = upcoming.event_count
    if count == 0:
        return f"coming up: 0 upcoming events in the next {_span(upcoming)} day(s); section omitted"
    dates = len(upcoming.days)
    first, last = upcoming.days[0].day, upcoming.days[-1].day
    return (
        f"coming up: {count} upcoming event(s) on {dates} date(s), "
        f"{first.isoformat()} to {last.isoformat()}"
    )


def _span(upcoming: UpcomingEvents) -> int:
    return (upcoming.last_day - upcoming.first_day).days + 1


def _warning(path: Path, error: Exception) -> str:
    if isinstance(error, SchemaTooOldError):
        reason = f"{error}; {_STALE_HINT}"
    elif isinstance(error, SchemaTooNewError):
        reason = f"{error}; update this program"
    elif isinstance(error, sqlite3.OperationalError) and "locked" in str(error).lower():
        reason = "the ledger is locked by another run; try again when `process` has finished"
    else:
        reason = f"{type(error).__name__}: {error}"
    return (
        f"warning: the event ledger ({path.name}) could not be read, "
        f"so the digest has no Coming up section: {reason}"
    )


def load_upcoming(ledger_path: Path, *, now: datetime, days: int, tz_name: str) -> UpcomingOutcome:
    """Never raises for a ledger problem; a bad `days` or `tz_name` is the caller's to validate."""
    if not ledger_path.is_file():
        return UpcomingOutcome(
            None, "coming up: no event ledger yet (run `process`); section omitted"
        )
    try:
        with SqliteEventRepository(
            ledger_path, read_only=True, busy_timeout_s=LOCK_WAIT_S
        ) as ledger:
            upcoming = ListUpcomingEventsUseCase(ledger).execute(
                now=now, days=days, tz_name=tz_name
            )
    except (
        sqlite3.Error,
        SchemaTooOldError,
        SchemaTooNewError,
        OSError,
        KeyError,
        ValueError,  # a stored row that does not parse: the ledger's fault, not the caller's
    ) as error:
        return UpcomingOutcome(
            None, "coming up: skipped (ledger unreadable)", _warning(ledger_path, error)
        )
    return UpcomingOutcome(upcoming if upcoming.event_count else None, describe_included(upcoming))
