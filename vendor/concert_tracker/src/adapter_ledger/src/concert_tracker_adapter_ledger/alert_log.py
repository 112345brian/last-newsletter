"""SQLite record of which unwell sources were already announced (in `runs.sqlite`).

Operational state like the run history beside it: deleting it only means the next run announces
whatever is still unwell once more.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Self

from concert_tracker_core.source_runs import HealthLevel, source_key

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from types import TracebackType

    from concert_tracker_core.source_alerts import SourceAlert

_BUSY_TIMEOUT_S = 30.0
_SCHEMA = """
CREATE TABLE IF NOT EXISTS announced_alerts (
    source_key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    level TEXT NOT NULL
);
"""


class SqliteAlertLog:
    def __init__(self, path: Path | str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(path), timeout=_BUSY_TIMEOUT_S, isolation_level=None, check_same_thread=False
        )
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

    def announced(self) -> Mapping[str, HealthLevel]:
        rows = self._conn.execute("SELECT source_key, level FROM announced_alerts").fetchall()
        return {key: HealthLevel(level) for key, level in rows}

    def record(self, alert: SourceAlert) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO announced_alerts (source_key, source, level) VALUES (?, ?, ?)"
                " ON CONFLICT (source_key) DO UPDATE SET level = excluded.level,"
                " source = excluded.source",
                (source_key(alert.source), alert.source, alert.level.value),
            )

    def clear(self, source_keys: Collection[str]) -> None:
        with self._conn:
            self._conn.executemany(
                "DELETE FROM announced_alerts WHERE source_key = ?", [(k,) for k in source_keys]
            )
