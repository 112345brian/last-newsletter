"""File-backed `EventRepository`: every event in one JSON file, rewritten atomically per write.

SEAM: this is the stand-in until the SQLite `EventRepository` adapter exists. It is fine for
thousands of events; it loads the whole file once and writes it whole on each change. The
contract is the port's in `concert_tracker_core.event_ports`; swap it in the CLI's
`_event_repository()` and nothing else changes.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import json
from dataclasses import replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

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
)

from last_newsletter_adapter_storage.atomic_file import write_text_atomic

if TYPE_CHECKING:
    from pathlib import Path

    from concert_tracker_core.event_ports import CandidateQuery

_SCHEMA = 1


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _when_to_dict(when: ItemTime) -> dict[str, Any]:
    if isinstance(when, AllDay):
        return {"all_day": when.day.isoformat()}
    return {"start": when.start.isoformat(), "tz": when.tz_name, "end": _iso(when.end)}


def _when_from_dict(data: dict[str, Any]) -> ItemTime:
    if "all_day" in data:
        return AllDay(date.fromisoformat(data["all_day"]))
    end = data["end"]
    return Timed(
        start=datetime.fromisoformat(data["start"]),
        tz_name=data["tz"],
        end=datetime.fromisoformat(end) if end else None,
    )


def _mention_to_dict(m: Mention) -> dict[str, Any]:
    return {
        "message_id": m.message_id,
        "seen_at": m.seen_at.isoformat(),
        "source": m.source,
        "evidence": m.evidence,
        "match_rule": m.match_rule.value,
        "cited_event_id": str(m.cited_event_id),
        "raw_date_text": m.raw_date_text,
        "raw_ref": m.raw_ref,
    }


def _mention_from_dict(d: dict[str, Any]) -> Mention:
    return Mention(
        message_id=d["message_id"],
        seen_at=datetime.fromisoformat(d["seen_at"]),
        source=d["source"],
        evidence=d["evidence"],
        match_rule=MatchRule(d["match_rule"]),
        cited_event_id=EventId(UUID(d["cited_event_id"])),
        raw_date_text=d["raw_date_text"],
        raw_ref=RawRef(d["raw_ref"]) if d["raw_ref"] else None,
    )


def _entity_to_dict(e: EntityRef) -> dict[str, str]:
    return {"name": e.name, "role": e.role.value, "origin": e.origin.value}


def _event_to_dict(e: Event) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "kind": e.kind.value,
        "title": e.title,
        "summary": e.summary,
        "when": _when_to_dict(e.when),
        "mentions": [_mention_to_dict(m) for m in e.mentions],
        "first_seen": e.first_seen.isoformat(),
        "last_seen": e.last_seen.isoformat(),
        "entities": [_entity_to_dict(x) for x in e.entities],
        "state": e.state.value,
        "snoozed_until": _iso(e.snoozed_until),
        "possible_duplicates": [str(i) for i in e.possible_duplicates],
        "uid": e.uid,
        "sequence": e.sequence,
        "url": e.url,
        "city": e.city,
        "tags": sorted(e.tags),
        "price": e.price,
        "age": e.age,
        "night_of": e.night_of.isoformat() if e.night_of else None,
    }


def _event_from_dict(d: dict[str, Any]) -> Event:
    snoozed = d["snoozed_until"]
    night_of = d["night_of"]
    return Event(
        id=EventId(UUID(d["id"])),
        kind=EventKind(d["kind"]),
        title=d["title"],
        summary=d["summary"],
        when=_when_from_dict(d["when"]),
        mentions=tuple(_mention_from_dict(m) for m in d["mentions"]),
        first_seen=datetime.fromisoformat(d["first_seen"]),
        last_seen=datetime.fromisoformat(d["last_seen"]),
        entities=tuple(
            EntityRef(x["name"], EntityRole(x["role"]), Origin(x["origin"])) for x in d["entities"]
        ),
        state=ItemState(d["state"]),
        snoozed_until=datetime.fromisoformat(snoozed) if snoozed else None,
        possible_duplicates=tuple(EventId(UUID(i)) for i in d["possible_duplicates"]),
        uid=d["uid"],
        sequence=d["sequence"],
        url=d["url"],
        city=d["city"],
        tags=frozenset(d["tags"]),
        price=d["price"],
        age=d["age"],
        night_of=date.fromisoformat(night_of) if night_of else None,
    )


class JsonEventRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._events: dict[EventId, Event] = self._load()

    def _load(self) -> dict[EventId, Event]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        # A corrupt ledger is NOT silently replaced by an empty one: that would re-mint every
        # UUID on the next run. Let the error surface so the owner can look at the file.
        data = json.loads(raw)
        if data.get("schema") != _SCHEMA:
            msg = f"{self._path}: unknown event ledger schema {data.get('schema')!r}"
            raise ValueError(msg)
        events = (_event_from_dict(e) for e in data["events"])
        return {e.id: e for e in events}

    def _flush(self) -> None:
        payload = {"schema": _SCHEMA, "events": [_event_to_dict(e) for e in self._events.values()]}
        write_text_atomic(self._path, json.dumps(payload, indent=1, sort_keys=True))

    def get(self, event_id: EventId) -> Event | None:
        return self._events.get(event_id)

    def find_candidates(self, query: CandidateQuery) -> list[Event]:
        return [
            e
            for e in self._events.values()
            if (query.uid is not None and e.uid == query.uid)
            or (query.url is not None and e.url == query.url)
            or query.date_from <= local_date(e.when) <= query.date_to
        ]

    def all_events(self) -> list[Event]:
        """Every stored event whatever its state (used by the one-time import into SQLite)."""
        return list(self._events.values())

    def list_open(self) -> list[Event]:
        return [e for e in self._events.values() if e.state in {ItemState.OPEN, ItemState.SNOOZED}]

    def upsert(self, event: Event) -> None:
        self._events[event.id] = event
        self._flush()

    def record_mention(self, event_id: EventId, mention: Mention) -> None:
        event = self._events[event_id]
        self._events[event_id] = replace(
            event,
            mentions=(*event.mentions, mention),
            last_seen=max(event.last_seen, mention.seen_at),
        )
        self._flush()
