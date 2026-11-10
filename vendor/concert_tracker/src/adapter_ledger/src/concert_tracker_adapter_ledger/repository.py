"""SQLite `EventRepository` (docs/design/event-ledger.md section 6).

Ownership of data, which is the point of the table split:

* `events` + extractor-origin `event_entities`: extracted facts. `upsert` rewrites them.
* `event_owner_state` + owner-origin `event_entities`: what the owner did. `upsert` only seeds
  the state for a brand-new event and never overwrites it; use `set_owner_state`.
* `mentions`: append-only, unique per (event, message, evidence), so re-ingest is a no-op.
* `possible_duplicates`: links between events; nothing is ever merged.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Self
from uuid import UUID

from process_lock.file_lock import cross_process_file_lock

from concert_tracker_adapter_ledger.migrations import migrate, require_current
from concert_tracker_core.events import (
    AllDay,
    EntityRef,
    EntityRole,
    Event,
    EventId,
    EventKind,
    ItemState,
    ItemTime,
    MatchRule,
    Mention,
    Origin,
    RawRef,
    Timed,
    local_date,
    require_aware,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from types import TracebackType

    from concert_tracker_core.event_ports import CandidateQuery

_BUSY_TIMEOUT_S = 30.0
_OPEN_STATES = (ItemState.OPEN.value, ItemState.SNOOZED.value)
_OWNER_ORD_BASE = 1_000_000


@contextmanager
def ledger_write_lock(db_path: Path | str, *, timeout_s: float = 60.0) -> Generator[None]:
    """Exclusive cross-process lock for a whole CLI run that reads, decides and then writes.
    SQLite already serializes individual writes; this stops two runs interleaving decisions."""
    with cross_process_file_lock(
        Path(f"{db_path}.lock"), timeout_s=timeout_s, label="event ledger"
    ):
        yield


class SqliteEventRepository:
    """`EventRepository` over one SQLite file (WAL, foreign keys on, one transaction per write).

    `path` may be ``":memory:"`` for tests. The parent directory is created if missing.

    `read_only=True` opens an existing file that cannot be written through this connection: no
    directory or file is created, no pragma or migration runs, and a database that is not at the
    current schema raises `SchemaTooOldError` / `SchemaTooNewError`. Use it for reports that must
    not disturb a ledger another run may be writing. `busy_timeout_s` bounds how long a locked
    database is waited for.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        read_only: bool = False,
        busy_timeout_s: float = _BUSY_TIMEOUT_S,
    ) -> None:
        self._memory = str(path) == ":memory:"
        if read_only and self._memory:
            msg = "an in-memory ledger cannot be opened read-only"
            raise ValueError(msg)
        if not self._memory and not read_only:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        target = f"{Path(path).resolve().as_uri()}?mode=ro" if read_only else str(path)
        self._conn = sqlite3.connect(
            target,
            timeout=busy_timeout_s,
            isolation_level=None,
            check_same_thread=False,
            uri=read_only,
        )
        self._conn.row_factory = sqlite3.Row
        try:
            if read_only:
                self._conn.execute("PRAGMA query_only = ON")
                require_current(self._conn)
            else:
                self._conn.execute("PRAGMA foreign_keys = ON")
                if not self._memory:
                    self._conn.execute("PRAGMA journal_mode = WAL")
                    self._conn.execute("PRAGMA synchronous = NORMAL")
                migrate(self._conn)
        except BaseException:
            self._conn.close()
            raise

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- transactions ---------------------------------------------------------------------

    @contextmanager
    def _write(self) -> Generator[sqlite3.Connection]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    # -- reads ----------------------------------------------------------------------------

    def get(self, event_id: EventId) -> Event | None:
        row = self._conn.execute("SELECT * FROM events WHERE id = ?", (str(event_id),)).fetchone()
        return None if row is None else self._hydrate(row)

    def find_candidates(self, query: CandidateQuery) -> list[Event]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE (? IS NOT NULL AND uid = ?)"
            " OR (? IS NOT NULL AND url = ?) OR local_date BETWEEN ? AND ? ORDER BY id",
            (
                query.uid,
                query.uid,
                query.url,
                query.url,
                query.date_from.isoformat(),
                query.date_to.isoformat(),
            ),
        ).fetchall()
        return [self._hydrate(r) for r in rows]

    def list_open(self) -> list[Event]:
        rows = self._conn.execute(
            "SELECT e.* FROM events e JOIN event_owner_state s ON s.event_id = e.id"
            " WHERE s.state IN (?, ?) ORDER BY e.id",
            _OPEN_STATES,
        ).fetchall()
        return [self._hydrate(r) for r in rows]

    def list_all(self) -> list[Event]:
        """Every event whatever its state, oldest listed date first (for read-side views and
        for rebuilding derived indexes)."""
        rows = self._conn.execute("SELECT * FROM events ORDER BY local_date, id").fetchall()
        return [self._hydrate(r) for r in rows]

    # -- writes ---------------------------------------------------------------------------

    def upsert(self, event: Event) -> None:
        """Insert or update extracted facts, mentions and links in one transaction.

        An existing event keeps its owner state and owner-origin entities; mentions are only
        ever added; `possible_duplicates` is replaced by the given ids (existing score/rule
        are kept for pairs that stay).
        """
        eid = str(event.id)
        for mention in event.mentions:
            _check_cited(event.id, mention)
        with self._write() as db:
            db.execute(_UPSERT_EVENT, _event_params(event))
            db.execute(
                "INSERT OR IGNORE INTO event_owner_state (event_id, state, snoozed_until)"
                " VALUES (?, ?, ?)",
                (eid, event.state.value, _iso_or_none(event.snoozed_until)),
            )
            db.execute(
                "DELETE FROM event_entities WHERE event_id = ? AND origin = ?", (eid, "extractor")
            )
            for pos, entity in enumerate(event.entities):
                db.execute(
                    "INSERT OR IGNORE INTO event_entities (event_id, origin, name, role, ord)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        eid,
                        entity.origin.value,
                        entity.name,
                        entity.role.value,
                        pos + (_OWNER_ORD_BASE if entity.origin is Origin.OWNER else 0),
                    ),
                )
            for mention in event.mentions:
                _insert_mention(db, eid, mention)
            wanted = [str(d) for d in event.possible_duplicates]
            for other in wanted:
                db.execute(
                    "INSERT OR IGNORE INTO possible_duplicates (event_id, other_event_id)"
                    " VALUES (?, ?)",
                    (eid, other),
                )
            stale = {
                r[0]
                for r in db.execute(
                    "SELECT other_event_id FROM possible_duplicates WHERE event_id = ?", (eid,)
                )
            } - set(wanted)
            for other in stale:
                db.execute(
                    "DELETE FROM possible_duplicates WHERE event_id = ? AND other_event_id = ?",
                    (eid, other),
                )

    def record_mention(self, event_id: EventId, mention: Mention) -> None:
        """Append one mention (a repeat of the same message and evidence is ignored) and raise
        `last_seen`. Raises `KeyError` for an unknown event."""
        _check_cited(event_id, mention)
        with self._write() as db:
            found = db.execute(
                "SELECT last_seen FROM events WHERE id = ?", (str(event_id),)
            ).fetchone()
            if found is None:
                raise KeyError(event_id)
            _insert_mention(db, str(event_id), mention)
            current = datetime.fromisoformat(found["last_seen"])
            if mention.seen_at > current:
                db.execute(
                    "UPDATE events SET last_seen = ? WHERE id = ?",
                    (mention.seen_at.isoformat(), str(event_id)),
                )

    # -- beyond the port ------------------------------------------------------------------

    def set_owner_state(
        self,
        event_id: EventId,
        state: ItemState,
        snoozed_until: datetime | None = None,
    ) -> None:
        """Record an owner decision (done, dismissed, snoozed...). `KeyError` if unknown."""
        if snoozed_until is not None:
            require_aware(snoozed_until, "snoozed_until")
        with self._write() as db:
            cur = db.execute(
                "UPDATE event_owner_state SET state = ?, snoozed_until = ? WHERE event_id = ?",
                (state.value, _iso_or_none(snoozed_until), str(event_id)),
            )
            if cur.rowcount == 0:
                raise KeyError(event_id)

    def add_owner_entity(self, event_id: EventId, name: str, role: EntityRole) -> None:
        """Record an owner correction: an entity that re-extraction will not remove."""
        with self._write() as db:
            if db.execute("SELECT 1 FROM events WHERE id = ?", (str(event_id),)).fetchone() is None:
                raise KeyError(event_id)
            db.execute(
                "INSERT OR IGNORE INTO event_entities (event_id, origin, name, role, ord)"
                " VALUES (?, 'owner', ?, ?, ?)",
                (str(event_id), name, role.value, _OWNER_ORD_BASE),
            )

    def link_possible_duplicate(
        self,
        event_id: EventId,
        other_id: EventId,
        *,
        score: float | None = None,
        rule: MatchRule | None = None,
    ) -> None:
        """Link two events both ways, recording why (never merges). `KeyError` if unknown."""
        if event_id == other_id:
            msg = "an event cannot be a possible duplicate of itself"
            raise ValueError(msg)
        with self._write() as db:
            for known in (event_id, other_id):
                if (
                    db.execute("SELECT 1 FROM events WHERE id = ?", (str(known),)).fetchone()
                    is None
                ):
                    raise KeyError(known)
            for a, b in ((event_id, other_id), (other_id, event_id)):
                db.execute(
                    "INSERT INTO possible_duplicates (event_id, other_event_id, score, rule)"
                    " VALUES (?, ?, ?, ?) ON CONFLICT (event_id, other_event_id)"
                    " DO UPDATE SET score = excluded.score, rule = excluded.rule",
                    (str(a), str(b), score, None if rule is None else rule.value),
                )

    # -- hydration ------------------------------------------------------------------------

    def _hydrate(self, row: sqlite3.Row) -> Event:
        eid = row["id"]
        owner = self._conn.execute(
            "SELECT state, snoozed_until FROM event_owner_state WHERE event_id = ?", (eid,)
        ).fetchone()
        entities = tuple(
            EntityRef(r["name"], EntityRole(r["role"]), Origin(r["origin"]))
            for r in self._conn.execute(
                "SELECT name, role, origin FROM event_entities WHERE event_id = ?"
                " ORDER BY ord, origin, name",
                (eid,),
            )
        )
        mentions = tuple(
            Mention(
                message_id=r["message_id"],
                seen_at=datetime.fromisoformat(r["seen_at"]),
                source=r["source"],
                evidence=r["evidence"],
                match_rule=MatchRule(r["match_rule"]),
                cited_event_id=EventId(UUID(eid)),
                raw_date_text=r["raw_date_text"],
                raw_ref=None if r["raw_ref"] is None else RawRef(r["raw_ref"]),
            )
            for r in self._conn.execute(
                "SELECT * FROM mentions WHERE event_id = ? ORDER BY id", (eid,)
            )
        )
        dups = tuple(
            EventId(UUID(r["other_event_id"]))
            for r in self._conn.execute(
                "SELECT other_event_id FROM possible_duplicates WHERE event_id = ?"
                " ORDER BY other_event_id",
                (eid,),
            )
        )
        return Event(
            id=EventId(UUID(eid)),
            kind=EventKind(row["kind"]),
            title=row["title"],
            summary=row["summary"],
            when=_load_when(row),
            mentions=mentions,
            first_seen=datetime.fromisoformat(row["first_seen"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
            entities=entities,
            state=ItemState(owner["state"]) if owner else ItemState.OPEN,
            snoozed_until=_dt_or_none(owner["snoozed_until"]) if owner else None,
            possible_duplicates=dups,
            uid=row["uid"],
            sequence=row["sequence"],
            url=row["url"],
            city=row["city"],
            tags=frozenset(json.loads(row["tags"])),
            price=row["price"],
            age=row["age"],
            night_of=None if row["night_of"] is None else date.fromisoformat(row["night_of"]),
            showtimes=tuple(time.fromisoformat(t) for t in json.loads(row["showtimes"])),
        )


_UPSERT_EVENT = """
INSERT INTO events (id, kind, title, summary, when_kind, when_day, when_start, when_end, when_tz,
    local_date, first_seen, last_seen, uid, sequence, url, city, tags, price, age, night_of,
    showtimes)
VALUES (:id, :kind, :title, :summary, :when_kind, :when_day, :when_start, :when_end, :when_tz,
    :local_date, :first_seen, :last_seen, :uid, :sequence, :url, :city, :tags, :price, :age,
    :night_of, :showtimes)
ON CONFLICT (id) DO UPDATE SET
    kind = excluded.kind, title = excluded.title, summary = excluded.summary,
    when_kind = excluded.when_kind, when_day = excluded.when_day,
    when_start = excluded.when_start, when_end = excluded.when_end, when_tz = excluded.when_tz,
    local_date = excluded.local_date, first_seen = excluded.first_seen,
    last_seen = excluded.last_seen, uid = excluded.uid, sequence = excluded.sequence,
    url = excluded.url, city = excluded.city, tags = excluded.tags, price = excluded.price,
    age = excluded.age, night_of = excluded.night_of,
    showtimes = excluded.showtimes
"""


def _event_params(event: Event) -> dict[str, object]:
    when = event.when
    return {
        "id": str(event.id),
        "kind": event.kind.value,
        "title": event.title,
        "summary": event.summary,
        "when_kind": "all_day" if isinstance(when, AllDay) else "timed",
        "when_day": when.day.isoformat() if isinstance(when, AllDay) else None,
        "when_start": when.start.isoformat() if isinstance(when, Timed) else None,
        "when_end": when.end.isoformat() if isinstance(when, Timed) and when.end else None,
        "when_tz": when.tz_name if isinstance(when, Timed) else None,
        "local_date": local_date(when).isoformat(),
        "first_seen": event.first_seen.isoformat(),
        "last_seen": event.last_seen.isoformat(),
        "uid": event.uid,
        "sequence": event.sequence,
        "url": event.url,
        "city": event.city,
        "tags": json.dumps(sorted(event.tags), ensure_ascii=False),
        "price": event.price,
        "age": event.age,
        "night_of": None if event.night_of is None else event.night_of.isoformat(),
        "showtimes": json.dumps([t.strftime("%H:%M") for t in event.showtimes]),
    }


def _load_when(row: sqlite3.Row) -> ItemTime:
    if row["when_kind"] == "all_day":
        return AllDay(date.fromisoformat(row["when_day"]))
    return Timed(
        start=datetime.fromisoformat(row["when_start"]),
        tz_name=row["when_tz"],
        end=_dt_or_none(row["when_end"]),
    )


def _insert_mention(db: sqlite3.Connection, event_id: str, m: Mention) -> None:
    db.execute(
        "INSERT OR IGNORE INTO mentions (event_id, message_id, seen_at, source, evidence,"
        " match_rule, raw_date_text, raw_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_id,
            m.message_id,
            m.seen_at.isoformat(),
            m.source,
            m.evidence,
            m.match_rule.value,
            m.raw_date_text,
            m.raw_ref,
        ),
    )


def _check_cited(event_id: EventId, mention: Mention) -> None:
    if mention.cited_event_id != event_id:
        msg = f"mention cites {mention.cited_event_id}, not {event_id}"
        raise ValueError(msg)


def _iso_or_none(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _dt_or_none(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)
