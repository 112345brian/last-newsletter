from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from last_newsletter_adapter_ledger import (
    MIGRATIONS,
    SchemaTooNewError,
    SchemaTooOldError,
    SqliteEventRepository,
    migrate,
)
from last_newsletter_core.events import AllDay, Event, EventId, EventKind, MatchRule, Mention

if TYPE_CHECKING:
    from pathlib import Path

_T = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
_ID = EventId(UUID(int=1))


def _event() -> Event:
    mention = Mention(
        message_id="m1",
        seen_at=_T,
        source="s",
        evidence="x",
        match_rule=MatchRule.NEW,
        cited_event_id=_ID,
    )
    return Event(
        id=_ID,
        kind=EventKind.EVENT,
        title="Show",
        summary="",
        when=AllDay(date(2026, 12, 12)),
        mentions=(mention,),
        first_seen=_T,
        last_seen=_T,
    )


def _ledger(path: Path) -> Path:
    with SqliteEventRepository(path) as repo:
        repo.upsert(_event())
    return path


def test_read_only_reads_what_was_written(tmp_path: Path) -> None:
    path = _ledger(tmp_path / "ledger.sqlite")
    with SqliteEventRepository(path, read_only=True) as repo:
        assert [e.id for e in repo.list_open()] == [_ID]


def test_read_only_cannot_write(tmp_path: Path) -> None:
    path = _ledger(tmp_path / "ledger.sqlite")
    with SqliteEventRepository(path, read_only=True) as repo, pytest.raises(sqlite3.Error):
        repo.upsert(_event())


def test_read_only_creates_nothing_when_the_file_is_missing(tmp_path: Path) -> None:
    missing = tmp_path / "events" / "ledger.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        SqliteEventRepository(missing, read_only=True)
    assert not missing.parent.exists()


def test_read_only_refuses_an_unmigrated_database_and_leaves_it_alone(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path, isolation_level=None)
    migrate(conn, MIGRATIONS[:1])
    conn.close()
    with pytest.raises(SchemaTooOldError):
        SqliteEventRepository(path, read_only=True)
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    conn.close()


def test_read_only_refuses_a_newer_database(tmp_path: Path) -> None:
    path = _ledger(tmp_path / "new.sqlite")
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
    conn.close()
    with pytest.raises(SchemaTooNewError):
        SqliteEventRepository(path, read_only=True)


def test_read_only_is_not_blocked_by_a_writer_in_progress(tmp_path: Path) -> None:
    path = _ledger(tmp_path / "ledger.sqlite")
    writer = sqlite3.connect(path, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    try:
        with SqliteEventRepository(path, read_only=True, busy_timeout_s=0.1) as repo:
            assert [e.id for e in repo.list_open()] == [_ID]
    finally:
        writer.execute("ROLLBACK")
        writer.close()


def test_memory_cannot_be_read_only() -> None:
    with pytest.raises(ValueError, match="read-only"):
        SqliteEventRepository(":memory:", read_only=True)
