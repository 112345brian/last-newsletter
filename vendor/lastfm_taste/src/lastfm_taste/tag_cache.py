"""A local SQLite cache of tag answers, with separate lifetimes for "found" and "not found"."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

TAG_TTL = timedelta(days=30)
NOT_FOUND_TTL = timedelta(days=7)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS artist_tags (
    artist_key TEXT PRIMARY KEY,
    found INTEGER NOT NULL,
    tags TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
"""


class TagCache:
    """A local SQLite cache of tag answers (`found=False` remembers "Last.fm has no such artist").

    A genre cache is regenerable and personal: the caller chooses where it lives (the library
    never picks a path) and it must never be committed.
    """

    def __init__(self, path: Path | str, *, now: Callable[[], datetime]) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._now = now

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._conn.close()

    def get(self, key: str) -> tuple[bool, list[tuple[str, int]]] | None:
        """`(found, tags)` when fresh, else None."""
        row = self._conn.execute(
            "SELECT found, tags, fetched_at FROM artist_tags WHERE artist_key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        found, tags, fetched_at = row
        ttl = TAG_TTL if found else NOT_FOUND_TTL
        if self._now() - datetime.fromisoformat(fetched_at) > ttl:
            return None
        return bool(found), [(str(name), int(weight)) for name, weight in json.loads(tags)]

    def put(self, key: str, *, found: bool, tags: list[tuple[str, int]]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO artist_tags (artist_key, found, tags, fetched_at)"
            " VALUES (?, ?, ?, ?)",
            (key, int(found), json.dumps(tags), self._now().astimezone(UTC).isoformat()),
        )
