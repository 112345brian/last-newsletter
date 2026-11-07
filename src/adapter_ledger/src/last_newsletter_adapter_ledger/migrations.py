"""Schema migrations driven by `PRAGMA user_version`.

`MIGRATIONS[i]` upgrades a database at version `i` to version `i + 1`. Each runs, with its
version bump, in one transaction: a failure leaves the database exactly as it was. Never edit a
shipped migration; append a new one.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence


class SchemaTooNewError(RuntimeError):
    """The database was written by a newer version of this program; refuse to touch it."""


_V1 = (
    """
    CREATE TABLE events (
        id          TEXT PRIMARY KEY,
        kind        TEXT NOT NULL,
        title       TEXT NOT NULL,
        summary     TEXT NOT NULL,
        when_kind   TEXT NOT NULL CHECK (when_kind IN ('all_day', 'timed')),
        when_day    TEXT,
        when_start  TEXT,
        when_end    TEXT,
        when_tz     TEXT,
        local_date  TEXT NOT NULL,
        first_seen  TEXT NOT NULL,
        last_seen   TEXT NOT NULL,
        uid         TEXT,
        sequence    INTEGER NOT NULL DEFAULT 0,
        url         TEXT,
        city        TEXT NOT NULL DEFAULT '',
        tags        TEXT NOT NULL DEFAULT '[]',
        price       TEXT NOT NULL DEFAULT '',
        age         TEXT NOT NULL DEFAULT '',
        night_of    TEXT
    ) WITHOUT ROWID
    """,
    "CREATE INDEX events_uid ON events (uid) WHERE uid IS NOT NULL",
    "CREATE INDEX events_url ON events (url) WHERE url IS NOT NULL",
    "CREATE INDEX events_local_date ON events (local_date)",
    # What the owner did. Never written by extraction.
    """
    CREATE TABLE event_owner_state (
        event_id      TEXT PRIMARY KEY REFERENCES events (id) ON DELETE CASCADE,
        state         TEXT NOT NULL,
        snoozed_until TEXT
    ) WITHOUT ROWID
    """,
    # origin 'extractor' rows are replaced on re-extraction; 'owner' rows (the owner's
    # corrections) are kept.
    """
    CREATE TABLE event_entities (
        event_id TEXT NOT NULL REFERENCES events (id) ON DELETE CASCADE,
        origin   TEXT NOT NULL CHECK (origin IN ('owner', 'extractor')),
        name     TEXT NOT NULL,
        role     TEXT NOT NULL,
        ord      INTEGER NOT NULL,
        PRIMARY KEY (event_id, origin, name, role)
    ) WITHOUT ROWID
    """,
    # Append-only provenance: which email cited which event, by which rung, quoting what.
    """
    CREATE TABLE mentions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id      TEXT NOT NULL REFERENCES events (id) ON DELETE CASCADE,
        message_id    TEXT NOT NULL,
        seen_at       TEXT NOT NULL,
        source        TEXT NOT NULL,
        evidence      TEXT NOT NULL,
        match_rule    TEXT NOT NULL,
        raw_date_text TEXT NOT NULL DEFAULT '',
        raw_ref       TEXT,
        UNIQUE (event_id, message_id, evidence)
    )
    """,
    "CREATE INDEX mentions_message ON mentions (message_id)",
    # Ambiguous matches: a link, never a merge.
    """
    CREATE TABLE possible_duplicates (
        event_id       TEXT NOT NULL REFERENCES events (id) ON DELETE CASCADE,
        other_event_id TEXT NOT NULL REFERENCES events (id) ON DELETE CASCADE,
        score          REAL,
        rule           TEXT,
        PRIMARY KEY (event_id, other_event_id),
        CHECK (event_id <> other_event_id)
    ) WITHOUT ROWID
    """,
)

# Several start times on one date (a film at 12PM, 3:30PM and 7PM): a JSON list of "HH:MM".
_V2 = ("ALTER TABLE events ADD COLUMN showtimes TEXT NOT NULL DEFAULT '[]'",)

MIGRATIONS: tuple[tuple[str, ...], ...] = (_V1, _V2)


def migrate(conn: sqlite3.Connection, migrations: Sequence[Sequence[str]] = MIGRATIONS) -> int:
    """Bring `conn` (autocommit mode) to the latest version; return the version reached."""
    target = len(migrations)
    current = _version(conn)
    if current > target:
        msg = f"ledger database is schema v{current}; this program understands up to v{target}"
        raise SchemaTooNewError(msg)
    for version in range(current, target):
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Another process may have migrated while we waited for the write lock.
            if _version(conn) == version:
                for statement in migrations[version]:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {version + 1}")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    return target


def _version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])
