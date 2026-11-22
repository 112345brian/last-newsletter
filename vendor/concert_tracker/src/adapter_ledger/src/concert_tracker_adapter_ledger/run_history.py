"""SQLite run history: what each run of each source came to (`runs.sqlite`, beside the ledger).

A separate file from the ledger on purpose: it is operational telemetry, never the source of
truth for events, so it can be deleted or rebuilt without touching them. The newest
`KEEP_PER_SOURCE` outcomes of each source are kept.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Self

from concert_tracker_core.source_runs import RunStatus, SourceOutcome

if TYPE_CHECKING:
    from types import TracebackType

KEEP_PER_SOURCE = 50
_BUSY_TIMEOUT_S = 30.0
_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    seconds REAL NOT NULL,
    found INTEGER NOT NULL,
    created INTEGER NOT NULL,
    mentioned INTEGER NOT NULL,
    error TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS source_runs_by_source ON source_runs (source, id);
"""


class SqliteRunHistory:
    def __init__(self, path: Path | str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(path), timeout=_BUSY_TIMEOUT_S, isolation_level=None, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def record(self, outcome: SourceOutcome) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO source_runs (source, status, started_at, seconds, found, created,"
                " mentioned, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    outcome.source,
                    outcome.status.value,
                    outcome.started_at.isoformat(),
                    outcome.seconds,
                    outcome.found,
                    outcome.created,
                    outcome.mentioned,
                    outcome.error,
                ),
            )
            self._conn.execute(
                "DELETE FROM source_runs WHERE source = ? AND id NOT IN"
                " (SELECT id FROM source_runs WHERE source = ? ORDER BY id DESC LIMIT ?)",
                (outcome.source, outcome.source, KEEP_PER_SOURCE),
            )

    def recent(self, source: str, limit: int) -> list[SourceOutcome]:
        rows = self._conn.execute(
            "SELECT * FROM source_runs WHERE source = ? ORDER BY id DESC LIMIT ?", (source, limit)
        ).fetchall()
        return [_outcome(row) for row in rows]

    def sources(self) -> list[str]:
        rows = self._conn.execute("SELECT DISTINCT source FROM source_runs ORDER BY source")
        return [row["source"] for row in rows]


def _outcome(row: sqlite3.Row) -> SourceOutcome:
    return SourceOutcome(
        source=row["source"],
        status=RunStatus(row["status"]),
        started_at=datetime.fromisoformat(row["started_at"]),
        seconds=row["seconds"],
        found=row["found"],
        created=row["created"],
        mentioned=row["mentioned"],
        error=row["error"],
    )
