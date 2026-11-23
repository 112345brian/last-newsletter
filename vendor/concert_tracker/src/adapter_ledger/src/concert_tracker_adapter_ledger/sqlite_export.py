"""The export as a small SQLite database, for readers that would rather query than parse JSON.

One fresh file every time (never an update in place), written in one transaction in the export's
own order, so the same export gives the same bytes. The tables mirror the JSON document
(`schema_version` is also `PRAGMA user_version`): `meta`, `events`, and one child table per list.
It holds exactly what `EventExport` holds and nothing from the ledger itself.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

from concert_tracker_core.published_events import SCHEMA_VERSION, export_as_data

if TYPE_CHECKING:
    from pathlib import Path

    from concert_tracker_core.published_events import EventExport

_DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE events (
    position INTEGER PRIMARY KEY,
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    date TEXT NOT NULL,
    all_day INTEGER NOT NULL,
    start TEXT,
    "end" TEXT,
    venue TEXT,
    city TEXT,
    event_type TEXT NOT NULL,
    url TEXT
);
CREATE TABLE event_showtimes (
    event_position INTEGER NOT NULL, position INTEGER NOT NULL, at TEXT NOT NULL
);
CREATE TABLE event_venue_categories (event_position INTEGER NOT NULL, category TEXT NOT NULL);
CREATE TABLE event_sources (event_position INTEGER NOT NULL, source TEXT NOT NULL);
CREATE TABLE event_artists (
    event_position INTEGER NOT NULL,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL
);
CREATE TABLE event_tags (event_position INTEGER NOT NULL, tag TEXT NOT NULL);
"""


def _meta(export: EventExport) -> list[tuple[str, str | None]]:
    data = export_as_data(export)
    region = export.context
    return [
        ("schema_version", str(SCHEMA_VERSION)),
        ("generated_at", None if data["generated_at"] is None else str(data["generated_at"])),
        ("region_name", region.region_name),
        ("time_zone", region.time_zone),
        ("first_day", export.first_day.isoformat()),
        ("last_day", export.last_day.isoformat()),
        ("event_count", str(len(export.events))),
    ]


def _insert_events(db: sqlite3.Connection, export: EventExport) -> None:
    for position, event in enumerate(export.events, start=1):
        db.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                position,
                event.event_id,
                event.title,
                event.day.isoformat(),
                int(event.all_day),
                event.start,
                event.end,
                event.venue,
                event.city,
                event.event_type,
                event.url,
            ),
        )
        db.executemany(
            "INSERT INTO event_showtimes VALUES (?, ?, ?)",
            [(position, i, at) for i, at in enumerate(event.showtimes, start=1)],
        )
        db.executemany(
            "INSERT INTO event_venue_categories VALUES (?, ?)",
            [(position, c) for c in event.venue_categories],
        )
        db.executemany(
            "INSERT INTO event_sources VALUES (?, ?)", [(position, s) for s in event.sources]
        )
        db.executemany(
            "INSERT INTO event_artists VALUES (?, ?, ?, ?)",
            [(position, i, a.name, a.role.value) for i, a in enumerate(event.artists, start=1)],
        )
        db.executemany("INSERT INTO event_tags VALUES (?, ?)", [(position, t) for t in event.tags])


def write_sqlite_export(path: Path, export: EventExport) -> None:
    """Write `export` to `path`, replacing any file there. The file appears whole or not at all."""
    partial = path.with_name(path.name + ".partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial.unlink(missing_ok=True)
    with closing(sqlite3.connect(partial)) as db:
        db.execute("PRAGMA journal_mode = OFF")
        db.executescript(_DDL)
        db.executemany("INSERT INTO meta VALUES (?, ?)", _meta(export))
        _insert_events(db, export)
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        db.commit()
    partial.replace(path)
