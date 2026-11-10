# concert-tracker-adapter-ledger

SQLite implementation of `concert_tracker_core.event_ports.EventRepository`
(design: `docs/design/event-ledger.md`).

```python
from concert_tracker_adapter_ledger import SqliteEventRepository, ledger_write_lock

repo = SqliteEventRepository(data_dir / "ledger.db")  # creates + migrates; never inside the repo
```

* `events` (UUID primary key) holds extracted fields; `event_owner_state` holds what the owner
  did (state, snooze) and owner-origin entities are the owner's corrections. `upsert` rewrites
  extracted fields and extractor entities but never touches either, so re-extraction cannot
  undo owner decisions. Change owner state with `set_owner_state`.
* `mentions` is append-only, unique on `(event, message_id, evidence)`, so re-ingesting a
  message is a no-op. Each row cites the event UUID, the match rung and the evidence quote.
* `possible_duplicates` links two events without merging them (`score` and `rule` are optional;
  `Event.possible_duplicates` carries only ids, so `link_possible_duplicate` records them).
* `PRAGMA user_version` migrations, WAL, every write in one `BEGIN IMMEDIATE` transaction.
* `ledger_write_lock(path)` wraps the vendored `process_lock` for a whole CLI run.
