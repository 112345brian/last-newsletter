from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from concert_tracker_core.event_ports import CandidateQuery
from concert_tracker_core.events import (
    AllDay,
    EntityRef,
    EntityRole,
    Event,
    EventId,
    EventKind,
    MatchRule,
    Mention,
    RawRef,
    Timed,
)

from last_newsletter_adapter_storage import JsonEventRepository, ProcessedMarkers

if TYPE_CHECKING:
    from pathlib import Path

_T = datetime(2026, 11, 5, tzinfo=UTC)


def _event(n: int, when: AllDay | Timed | None = None) -> Event:
    eid = EventId(UUID(int=n))
    return Event(
        id=eid,
        kind=EventKind.EVENT,
        title=f"Show {n}",
        summary="s",
        when=when or AllDay(date(2026, 12, 12)),
        mentions=(
            Mention("m1", _T, "src", "ev", MatchRule.NEW, eid, "Dec 12", RawRef("raw:" + "a" * 64)),
        ),
        first_seen=_T,
        last_seen=_T,
        entities=(EntityRef("The Venue", EntityRole.VENUE),),
        tags=frozenset({"b", "a"}),
        uid="u1" if n == 1 else None,
    )


def test_roundtrip_through_a_fresh_instance(tmp_path: Path) -> None:
    path = tmp_path / "e" / "events.json"
    repo = JsonEventRepository(path)
    timed = Timed(
        datetime(2026, 12, 13, 20, tzinfo=UTC), "UTC", datetime(2026, 12, 13, 23, tzinfo=UTC)
    )
    repo.upsert(_event(1))
    repo.upsert(_event(2, timed))
    again = JsonEventRepository(path)
    assert again.get(EventId(UUID(int=1))) == _event(1)
    assert again.get(EventId(UUID(int=2))) == _event(2, timed)
    assert again.get(EventId(UUID(int=9))) is None


def test_record_mention_and_candidates(tmp_path: Path) -> None:
    repo = JsonEventRepository(tmp_path / "events.json")
    repo.upsert(_event(1))
    later = datetime(2026, 11, 6, tzinfo=UTC)
    mention = Mention("m2", later, "x", "ev2", MatchRule.UID, EventId(UUID(int=1)))
    repo.record_mention(EventId(UUID(int=1)), mention)
    event = JsonEventRepository(tmp_path / "events.json").get(EventId(UUID(int=1)))
    assert event is not None
    assert len(event.mentions) == 2
    assert event.last_seen == later
    with pytest.raises(KeyError):
        repo.record_mention(EventId(UUID(int=7)), mention)
    day = date(2026, 12, 12)
    assert len(repo.find_candidates(CandidateQuery(None, None, day, day))) == 1
    assert repo.find_candidates(CandidateQuery("u1", None, date(2030, 1, 1), date(2030, 1, 2)))
    assert not repo.find_candidates(CandidateQuery("zz", None, date(2030, 1, 1), date(2030, 1, 2)))


def test_a_corrupt_ledger_is_an_error_not_an_empty_ledger(tmp_path: Path) -> None:
    path = tmp_path / "events.json"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(ValueError, match=r"Expecting|property"):
        JsonEventRepository(path)


def test_markers_roundtrip_and_tolerate_garbage(tmp_path: Path) -> None:
    markers = ProcessedMarkers(tmp_path / "s" / "p.json")
    assert markers.processed() == set()
    markers.mark([RawRef("raw:a"), RawRef("raw:b")])
    markers.mark([RawRef("raw:b"), RawRef("raw:c")])
    assert markers.processed() == {"raw:a", "raw:b", "raw:c"}
    (tmp_path / "s" / "p.json").write_text("garbage", encoding="utf-8")
    assert markers.processed() == set()
