from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from last_newsletter_adapter_ledger import (
    MIGRATIONS,
    SchemaTooNewError,
    SqliteEventRepository,
    migrate,
)

if TYPE_CHECKING:
    from pathlib import Path


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path, isolation_level=None)


def _version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r[0] for r in rows}


def test_version_zero_database_is_upgraded_to_the_latest(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    conn = _connect(db)
    assert _version(conn) == 0
    assert _tables(conn) == set()

    assert migrate(conn) == len(MIGRATIONS)

    assert _version(conn) == len(MIGRATIONS)
    assert {
        "events",
        "event_owner_state",
        "event_entities",
        "mentions",
        "possible_duplicates",
    } <= _tables(conn)
    conn.close()


def test_opening_a_fresh_file_creates_the_schema(tmp_path: Path) -> None:
    db = tmp_path / "new" / "dir" / "ledger.db"
    SqliteEventRepository(db).close()
    conn = _connect(db)
    assert _version(conn) == len(MIGRATIONS)
    conn.close()


def test_migrating_twice_is_a_no_op(tmp_path: Path) -> None:
    conn = _connect(tmp_path / "ledger.db")
    migrate(conn)
    conn.execute("PRAGMA foreign_keys = ON")
    assert migrate(conn) == len(MIGRATIONS)
    conn.close()


def test_an_older_database_keeps_its_data_through_a_later_migration(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    conn = _connect(db)
    migrate(conn)  # as shipped today
    conn.execute(
        "INSERT INTO events (id, kind, title, summary, when_kind, when_day, local_date,"
        " first_seen, last_seen) VALUES ('e1', 'event', 'Kept', '', 'all_day', '2026-12-12',"
        " '2026-12-12', '2026-11-05T00:00:00+00:00', '2026-11-05T00:00:00+00:00')"
    )

    future = (*MIGRATIONS, ("ALTER TABLE events ADD COLUMN venue_hint TEXT",))
    assert migrate(conn, future) == len(MIGRATIONS) + 1

    assert _version(conn) == len(MIGRATIONS) + 1
    assert conn.execute("SELECT title, venue_hint FROM events").fetchall() == [("Kept", None)]
    conn.close()


def test_a_failing_migration_changes_nothing(tmp_path: Path) -> None:
    conn = _connect(tmp_path / "ledger.db")
    broken = (("CREATE TABLE half (x)", "THIS IS NOT SQL"),)

    with pytest.raises(sqlite3.OperationalError):
        migrate(conn, broken)

    assert _version(conn) == 0
    assert _tables(conn) == set()
    conn.close()


def test_a_database_from_a_newer_program_is_refused_untouched(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    conn = _connect(db)
    conn.execute("CREATE TABLE marker (x)")
    conn.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 5}")
    conn.close()

    with pytest.raises(SchemaTooNewError):
        SqliteEventRepository(db)

    conn = _connect(db)
    assert _version(conn) == len(MIGRATIONS) + 5
    assert _tables(conn) == {"marker"}
    conn.close()


def test_a_v1_ledger_upgrades_and_its_events_have_no_showtimes(tmp_path: Path) -> None:
    """The owner's existing ledger predates `showtimes`: it must open, keep its rows, and read
    them back with an empty list."""
    db = tmp_path / "ledger.db"
    conn = _connect(db)
    assert migrate(conn, MIGRATIONS[:1]) == 1
    conn.execute(
        "INSERT INTO events (id, kind, title, summary, when_kind, when_day, local_date,"
        " first_seen, last_seen) VALUES ('00000000-0000-0000-0000-000000000001', 'event', 'T',"
        " '', 'all_day', '2026-12-12', '2026-12-12', '2026-11-06T00:00:00+00:00',"
        " '2026-11-06T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO mentions (event_id, message_id, seen_at, source, evidence, match_rule)"
        " VALUES ('00000000-0000-0000-0000-000000000001', 'm', '2026-11-06T00:00:00+00:00',"
        " 's', 'e', 'new')"
    )
    conn.close()
    with SqliteEventRepository(db) as repo:
        (event,) = repo.list_all()
    assert event.showtimes == ()
