"""What every command that writes the event ledger needs, in one place.

`process` (stage 2, from stored mail) and `fetch-events` (from a structured source) both open the
same ledger and similarity index, take the same write lock, and offer the same `--dry-run`. That
setup lives here once, so the two cannot drift apart: a dry run is always a throwaway copy, the
lock is always held around the writes, and the index is always brought in line with the ledger.

Layout under `<data_dir>/events/`:
    ledger.sqlite    the event ledger (source of truth; SQLite `EventRepository`)
    similar.sqlite   the semantic index (a cache; rebuilt from the ledger when out of sync)
"""

from __future__ import annotations

__arbor__ = {"ring": "cli"}

import shutil
import tempfile
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from last_newsletter_adapter_ledger import SqliteEventRepository, ledger_write_lock
from last_newsletter_adapter_semantic import HashedNgramIndex
from last_newsletter_cli.similarity import sync_index
from last_newsletter_core.events import EventId

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

LEDGER_NAME = "ledger.sqlite"
INDEX_NAME = "similar.sqlite"
_LOCK_TIMEOUT_S = 5.0


class ConfigError(Exception):
    """A setting is missing or invalid. Its message names the variable to fix."""


class IdGenerator(Protocol):
    def new_event_id(self) -> EventId: ...


class Uuid4Ids:
    """`IdGenerator`: random UUIDs (randomness is an effect, so it lives outside core)."""

    def new_event_id(self) -> EventId:
        return EventId(uuid4())


def copy_for_dry_run(events_dir: Path, scratch: Path) -> Path:
    """A throwaway copy of the state a command writes, so a dry run can change nothing real.

    The index is not copied at all, so it is rebuilt from the copied ledger.
    """
    target = scratch / "events"
    if events_dir.is_dir():
        shutil.copytree(
            events_dir, target, ignore=shutil.ignore_patterns(f"{LEDGER_NAME}*", f"{INDEX_NAME}*")
        )
    else:
        target.mkdir(parents=True)
    ledger = events_dir / LEDGER_NAME
    if ledger.exists():
        # Copy the database with its WAL under the write lock (so no run is mid-write), then
        # let SQLite recover the copy. Opening the original, even read-only, can leave -shm/-wal
        # files behind, and a dry run must leave the real directory exactly as it found it.
        with ledger_write_lock(ledger, timeout_s=_LOCK_TIMEOUT_S):
            for suffix in ("", "-wal", "-shm"):
                part = events_dir / f"{LEDGER_NAME}{suffix}"
                if part.exists():
                    shutil.copy2(part, target / part.name)
    return target


@dataclass(frozen=True, slots=True)
class LedgerSession:
    """The open ledger and index, with the write lock held for as long as the session lasts.

    `notes` collects the one-line remarks a command prints before its own summary (a dry run, a
    backup, a rebuilt index); the list stays readable after the session closes.
    """

    events_dir: Path
    ledger: SqliteEventRepository
    index: HashedNgramIndex
    notes: list[str]

    def sync_index(self) -> None:
        """Bring the index in line with the ledger (it is a cache), noting a rebuild."""
        if sync_index(self.index, self.ledger.list_all()):
            self.notes.append("rebuilt the similarity index from the ledger")


@contextmanager
def ledger_session(
    data_dir: Path,
    *,
    dry_run: bool,
    prepare: Callable[[Path, list[str]], None] | None = None,
) -> Generator[LedgerSession]:
    """Open the event ledger and index for writing under the one-writer lock.

    A dry run works on a scratch copy and saves nothing real. `prepare(events_dir, notes)` runs
    after the directory is chosen and before anything is opened, for work that must happen on
    closed files (such as moving the old ledger aside).
    """
    notes: list[str] = []
    with ExitStack() as stack:
        if dry_run:
            scratch = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="ln-dry-")))
            events_dir = copy_for_dry_run(data_dir / "events", scratch)
            notes.append("DRY RUN: nothing below was saved")
        else:
            events_dir = data_dir / "events"
            events_dir.mkdir(parents=True, exist_ok=True)
        if prepare is not None:
            prepare(events_dir, notes)
        ledger = stack.enter_context(SqliteEventRepository(events_dir / LEDGER_NAME))
        index = HashedNgramIndex(events_dir / INDEX_NAME)
        stack.callback(index.close)
        # One run at a time over the ledger, the index and anything else a command keeps beside.
        with ledger_write_lock(events_dir / LEDGER_NAME, timeout_s=_LOCK_TIMEOUT_S):
            yield LedgerSession(events_dir, ledger, index, notes)
