"""One-time migration of the old JSON event ledger into the SQLite ledger.

The JSON file is renamed (never deleted) once its events are safely in SQLite, so a second run
finds nothing to do and the owner keeps the original as a backup.
"""

from __future__ import annotations

__arbor__ = {"ring": "cli"}

from dataclasses import replace
from typing import TYPE_CHECKING

from last_newsletter_adapter_storage import JsonEventRepository

if TYPE_CHECKING:
    from pathlib import Path

    from last_newsletter_adapter_ledger import SqliteEventRepository

IMPORTED_SUFFIX = ".imported"


def import_json_ledger(json_path: Path, ledger: SqliteEventRepository) -> int:
    """Copy every event in `json_path` that `ledger` lacks. Returns how many were imported.

    Events already in the ledger win (they may have newer mentions or owner decisions). Nothing
    is lost on a crash midway: the JSON file is renamed only after every event was written, and
    a re-run skips what is already there. An unreadable JSON file raises and is left untouched.
    """
    if not json_path.exists():
        return 0
    old = JsonEventRepository(json_path).all_events()
    fresh = [e for e in old if ledger.get(e.id) is None]
    # Two passes: possible-duplicate links may point at an event written later in the list.
    for event in fresh:
        ledger.upsert(replace(event, possible_duplicates=()))
    for event in fresh:
        if event.possible_duplicates:
            ledger.upsert(event)
    json_path.rename(json_path.with_name(json_path.name + IMPORTED_SUFFIX))
    return len(fresh)
