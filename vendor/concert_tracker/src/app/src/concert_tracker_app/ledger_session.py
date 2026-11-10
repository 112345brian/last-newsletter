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

__arbor__ = {"ring": "app"}

import shutil
import tempfile
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from concert_tracker_adapter_ledger import SqliteEventRepository, ledger_write_lock
from concert_tracker_app.similarity import CombinedSimilarIndex, CoreSimilarIndex, sync_index
from concert_tracker_ngram_index import HashedNgramIndex

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Sequence

    from concert_tracker_app.similarity import SimilarBackend
    from concert_tracker_core.event_ports import SimilarEventIndex

LEDGER_NAME = "ledger.sqlite"
INDEX_NAME = "similar.sqlite"
_LOCK_TIMEOUT_S = 5.0


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
    """The open ledger and indexes, with the write lock held for as long as the session lasts.

    `index` is the always-on n-gram index; `backends` are optional extras (such as embeddings)
    that were handed in. `similar_index` is what core's ingest should be given: all of them
    behind the one port. `notes` collects the one-line remarks a command prints before its own
    summary (a dry run, a backup, a rebuilt index, a backend that could not work); the list stays
    readable after the session closes.
    """

    events_dir: Path
    ledger: SqliteEventRepository
    index: HashedNgramIndex
    notes: list[str]
    similar_index: SimilarEventIndex
    backends: tuple[SimilarBackend, ...] = ()

    def sync_index(self) -> None:
        """Bring the indexes in line with the ledger (they are caches), noting a rebuild."""
        events = self.ledger.list_all()
        if sync_index(self.index, events):
            self.notes.append("rebuilt the similarity index from the ledger")
        for backend in self.backends:
            backend.sync(events)


@contextmanager
def ledger_session(
    data_dir: Path,
    *,
    dry_run: bool,
    prepare: Callable[[Path, list[str]], None] | None = None,
    extra_indexes: Sequence[Callable[[Path], SimilarBackend]] = (),
) -> Generator[LedgerSession]:
    """Open the event ledger and indexes for writing under the one-writer lock.

    A dry run works on a scratch copy and saves nothing real. `prepare(events_dir, notes)` runs
    after the directory is chosen and before anything is opened, for work that must happen on
    closed files (such as moving the old ledger aside). Each `extra_indexes` factory is called
    with the directory the session uses (the scratch copy on a dry run) and its backend is closed
    when the session ends; anything it reports in `problems` is added to `notes` at the end.
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
        backends = tuple(factory(events_dir) for factory in extra_indexes)
        for backend in backends:
            stack.callback(backend.close)
        similar = CombinedSimilarIndex([CoreSimilarIndex(index), *backends])
        # One run at a time over the ledger, the indexes and anything else a command keeps beside.
        with ledger_write_lock(events_dir / LEDGER_NAME, timeout_s=_LOCK_TIMEOUT_S):
            try:
                yield LedgerSession(events_dir, ledger, index, notes, similar, backends)
            finally:
                for backend in backends:
                    notes.extend(backend.problems)
