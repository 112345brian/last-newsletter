from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from last_newsletter_adapter_ledger import SqliteEventRepository, ledger_write_lock
from last_newsletter_core.event_ports import CandidateQuery
from last_newsletter_core.events import (
    AllDay,
    EntityRef,
    EntityRole,
    Event,
    EventId,
    EventKind,
    ItemState,
    MatchRule,
    Mention,
    Origin,
    RawRef,
    Timed,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_T = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
_A = EventId(UUID(int=1))
_B = EventId(UUID(int=2))
_C = EventId(UUID(int=3))


def _mention(event_id: EventId, message_id: str = "m1", **overrides: object) -> Mention:
    base = Mention(
        message_id=message_id,
        seen_at=_T,
        source="promoter",
        evidence="SAT DEC 12 Band at Venue",
        match_rule=MatchRule.NEW,
        cited_event_id=event_id,
    )
    return replace(base, **overrides)


def _event(event_id: EventId = _A, **overrides: object) -> Event:
    base = Event(
        id=event_id,
        kind=EventKind.EVENT,
        title="Band at Venue",
        summary="Loud",
        when=AllDay(date(2026, 12, 12)),
        mentions=(_mention(event_id),),
        first_seen=_T,
        last_seen=_T,
    )
    return replace(base, **overrides)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "data" / "ledger.db"


@pytest.fixture
def repo(db: Path) -> Iterator[SqliteEventRepository]:
    with SqliteEventRepository(db) as repository:
        yield repository


def _event_rows(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    finally:
        conn.close()


# -- empty database ---------------------------------------------------------------------------


def test_empty_database_answers_with_nothing(repo: SqliteEventRepository) -> None:
    query = CandidateQuery(
        uid="u", url="http://x", date_from=date(2026, 1, 1), date_to=date(2027, 1, 1)
    )
    assert repo.get(_A) is None
    assert repo.find_candidates(query) == []
    assert repo.list_open() == []


# -- round trip -------------------------------------------------------------------------------


def test_every_field_round_trips(repo: SqliteEventRepository) -> None:
    when = Timed(
        start=datetime(2026, 12, 12, 21, 0, tzinfo=UTC),
        tz_name="America/New_York",
        end=datetime(2026, 12, 13, 3, 0, tzinfo=UTC),
    )
    event = _event(
        when=when,
        kind=EventKind.DEADLINE,
        entities=(
            EntityRef("Headliner", EntityRole.HEADLINER),
            EntityRef("The Venue", EntityRole.VENUE),
        ),
        mentions=(_mention(_A, raw_date_text="Sat 12/12", raw_ref=RawRef("raw-1")),),
        uid="abc@example.com#2026",
        sequence=3,
        url="https://example.com/e",
        city="Brooklyn",
        tags=frozenset({"punk", "all-ages"}),
        price="$20 | 21+",
        age="21+",
        night_of=date(2026, 12, 12),
        showtimes=(time(12), time(15, 30), time(19)),
        snoozed_until=_T + timedelta(days=1),
        state=ItemState.SNOOZED,
    )
    repo.upsert(event)
    assert repo.get(_A) == event


# -- idempotent ingest ------------------------------------------------------------------------


def test_upsert_of_the_same_event_twice_changes_nothing(repo: SqliteEventRepository) -> None:
    event = _event()
    repo.upsert(event)
    repo.upsert(event)
    assert repo.get(_A) == event
    assert len(repo.list_open()) == 1


def test_second_mention_cites_the_existing_uuid(repo: SqliteEventRepository) -> None:
    repo.upsert(_event())
    later = _T + timedelta(days=2)
    repo.record_mention(
        _A,
        _mention(_A, "m2", seen_at=later, evidence="Band at Venue!", match_rule=MatchRule.URL),
    )
    stored = repo.get(_A)
    assert stored is not None
    assert [m.message_id for m in stored.mentions] == ["m1", "m2"]
    assert {m.cited_event_id for m in stored.mentions} == {_A}
    assert stored.mentions[1].match_rule is MatchRule.URL
    assert stored.last_seen == later
    assert len(repo.list_open()) == 1


def test_repeating_a_mention_is_ignored(repo: SqliteEventRepository) -> None:
    repo.upsert(_event())
    repo.record_mention(_A, _mention(_A))
    stored = repo.get(_A)
    assert stored is not None
    assert len(stored.mentions) == 1


def test_an_older_mention_does_not_move_last_seen_back(repo: SqliteEventRepository) -> None:
    repo.upsert(_event())
    repo.record_mention(_A, _mention(_A, "m0", seen_at=_T - timedelta(days=9), evidence="old"))
    stored = repo.get(_A)
    assert stored is not None
    assert stored.last_seen == _T
    assert len(stored.mentions) == 2


def test_record_mention_for_unknown_event_raises_key_error(repo: SqliteEventRepository) -> None:
    with pytest.raises(KeyError):
        repo.record_mention(_B, _mention(_B))
    assert repo.get(_B) is None


def test_a_mention_citing_another_event_is_refused(repo: SqliteEventRepository) -> None:
    repo.upsert(_event())
    with pytest.raises(ValueError, match="cites"):
        repo.record_mention(_A, _mention(_B))
    with pytest.raises(ValueError, match="cites"):
        repo.upsert(_event(_B, mentions=(_mention(_A),)))
    assert repo.get(_B) is None


# -- owner state and corrections --------------------------------------------------------------


def test_re_extraction_never_overwrites_what_the_owner_did(repo: SqliteEventRepository) -> None:
    repo.upsert(_event(entities=(EntityRef("Wrong Band", EntityRole.HEADLINER),)))
    repo.set_owner_state(_A, ItemState.SNOOZED, _T + timedelta(days=3))
    repo.add_owner_entity(_A, "Right Band", EntityRole.HEADLINER)

    # A fresh extraction arrives with the default OPEN state and different facts.
    repo.upsert(
        _event(
            title="Band at Venue (updated)",
            sequence=2,
            entities=(EntityRef("Wrong Band 2", EntityRole.HEADLINER),),
        )
    )

    stored = repo.get(_A)
    assert stored is not None
    assert stored.title == "Band at Venue (updated)"
    assert (stored.state, stored.snoozed_until) == (ItemState.SNOOZED, _T + timedelta(days=3))
    assert {(e.name, e.origin) for e in stored.entities} == {
        ("Wrong Band 2", Origin.EXTRACTOR),
        ("Right Band", Origin.OWNER),
    }
    assert repo.list_open() == [stored]


def test_owner_state_decides_what_is_open(repo: SqliteEventRepository) -> None:
    repo.upsert(_event(_A))
    repo.upsert(_event(_B, mentions=(_mention(_B),)))
    repo.set_owner_state(_B, ItemState.DISMISSED)
    assert [e.id for e in repo.list_open()] == [_A]
    repo.set_owner_state(_B, ItemState.OPEN)
    assert [e.id for e in repo.list_open()] == [_A, _B]


def test_owner_state_for_unknown_event_raises(repo: SqliteEventRepository) -> None:
    with pytest.raises(KeyError):
        repo.set_owner_state(_C, ItemState.DONE)
    with pytest.raises(KeyError):
        repo.add_owner_entity(_C, "x", EntityRole.VENUE)


def test_naive_datetimes_are_rejected(repo: SqliteEventRepository) -> None:
    repo.upsert(_event())
    with pytest.raises(ValueError, match="timezone-aware"):
        repo.set_owner_state(_A, ItemState.SNOOZED, datetime.fromisoformat("2026-12-01T00:00:00"))
    with pytest.raises(ValueError, match="timezone-aware"):
        _event(
            first_seen=datetime.fromisoformat("2026-01-01T00:00:00"),
            last_seen=datetime.fromisoformat("2026-01-02T00:00:00"),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        _mention(_A, seen_at=datetime.fromisoformat("2026-01-01T00:00:00"))
    stored = repo.get(_A)
    assert stored is not None
    assert stored.state is ItemState.OPEN


# -- possible duplicates ----------------------------------------------------------------------


def test_ambiguous_match_links_and_does_not_merge(repo: SqliteEventRepository) -> None:
    repo.upsert(_event(_A))
    repo.upsert(
        _event(_B, title="Band @ Venue", mentions=(_mention(_B, "m2"),), possible_duplicates=(_A,))
    )
    repo.upsert(replace(repo.get(_A) or _event(_A), possible_duplicates=(_B,)))

    a, b = repo.get(_A), repo.get(_B)
    assert a is not None
    assert b is not None
    assert a.possible_duplicates == (_B,)
    assert b.possible_duplicates == (_A,)
    assert [m.message_id for m in a.mentions] == ["m1"]
    assert [m.message_id for m in b.mentions] == ["m2"]
    assert len(repo.list_open()) == 2


def test_links_record_score_and_rule_and_survive_a_re_upsert(
    repo: SqliteEventRepository, db: Path
) -> None:
    repo.upsert(_event(_A))
    repo.upsert(_event(_B, mentions=(_mention(_B),)))
    repo.link_possible_duplicate(_A, _B, score=0.83, rule=MatchRule.SIMILAR)
    repo.upsert(replace(repo.get(_B) or _event(_B), possible_duplicates=(_A,)))
    rows = _link_rows(db)
    assert rows == [(str(_A), str(_B), 0.83, "similar"), (str(_B), str(_A), 0.83, "similar")]


def test_upsert_replaces_the_link_set(repo: SqliteEventRepository) -> None:
    repo.upsert(_event(_A))
    repo.upsert(_event(_B, mentions=(_mention(_B),)))
    repo.upsert(_event(_C, mentions=(_mention(_C),), possible_duplicates=(_A, _B)))
    repo.upsert(_event(_C, mentions=(_mention(_C),), possible_duplicates=(_B,)))
    stored = repo.get(_C)
    assert stored is not None
    assert stored.possible_duplicates == (_B,)


def test_linking_unknown_or_the_same_event_is_refused(
    repo: SqliteEventRepository, db: Path
) -> None:
    repo.upsert(_event(_A))
    with pytest.raises(KeyError):
        repo.link_possible_duplicate(_A, _C)
    with pytest.raises(ValueError, match="itself"):
        repo.link_possible_duplicate(_A, _A)
    assert _link_rows(db) == []


def _link_rows(db: Path) -> list[tuple[str, str, float | None, str | None]]:
    rows = (
        sqlite3.connect(db)
        .execute(
            "SELECT event_id, other_event_id, score, rule FROM possible_duplicates"
            " ORDER BY event_id, other_event_id"
        )
        .fetchall()
    )
    return [(r[0], r[1], r[2], r[3]) for r in rows]


# -- crash safety -----------------------------------------------------------------------------


def test_a_failure_mid_upsert_leaves_no_partial_event(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    with SqliteEventRepository(db) as repo:
        repo.upsert(_event(_A))
        broken = _event(
            _B,
            mentions=(_mention(_B),),
            entities=(EntityRef("Band", EntityRole.HEADLINER),),
            possible_duplicates=(_C,),  # unknown event: the foreign key fails after rows went in
        )
        with pytest.raises(sqlite3.IntegrityError):
            repo.upsert(broken)
        assert repo.get(_B) is None
        assert [e.id for e in repo.list_open()] == [_A]
        repo.upsert(_event(_B, mentions=(_mention(_B),)))  # the connection is still usable
    assert _event_rows(db) == 2


def test_a_failed_re_upsert_keeps_the_previous_version(repo: SqliteEventRepository) -> None:
    original = _event(_A)
    repo.upsert(original)
    with pytest.raises(sqlite3.IntegrityError):
        repo.upsert(replace(original, title="Changed", possible_duplicates=(_C,)))
    assert repo.get(_A) == original


def test_committed_data_survives_reopen(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    with SqliteEventRepository(db) as first:
        first.upsert(_event())
    with SqliteEventRepository(db) as second:
        assert second.get(_A) == _event()


# -- hostile and unusual text -----------------------------------------------------------------


def test_nul_in_evidence_and_non_ascii_text_round_trip(repo: SqliteEventRepository) -> None:
    evidence = "café ☃ \U0001f3b8 \u202e rtl\x00after-nul"
    event = _event(
        title="Sigur Rós — ライブ",
        summary="über événement",
        city="São Paulo",
        tags=frozenset({"音楽"}),
        mentions=(_mention(_A, evidence=evidence, raw_date_text="٣ ديسمبر"),),
    )
    repo.upsert(event)
    assert repo.get(_A) == event


def test_sql_metacharacters_are_data(repo: SqliteEventRepository) -> None:
    title = "x'); DROP TABLE events;--"
    repo.upsert(_event(title=title, uid="' OR 1=1 --"))
    stored = repo.get(_A)
    assert stored is not None
    assert stored.title == title
    query = CandidateQuery("' OR 1=1 --", None, date(2000, 1, 1), date(2000, 1, 2))
    assert [e.id for e in repo.find_candidates(query)] == [_A]


def test_very_long_text_round_trips(repo: SqliteEventRepository) -> None:
    long_text = "wall of text é " * 200_000
    event = _event(summary=long_text, mentions=(_mention(_A, evidence=long_text),))
    repo.upsert(event)
    assert repo.get(_A) == event


# -- find_candidates --------------------------------------------------------------------------


def test_candidates_are_the_union_of_uid_url_and_date_window(repo: SqliteEventRepository) -> None:
    repo.upsert(_event(_A, uid="u-1", when=AllDay(date(2030, 1, 1))))
    repo.upsert(
        _event(_B, url="https://x/e", when=AllDay(date(2031, 1, 1)), mentions=(_mention(_B),))
    )
    repo.upsert(_event(_C, when=AllDay(date(2026, 12, 12)), mentions=(_mention(_C),)))

    def ids(query: CandidateQuery) -> list[EventId]:
        return [e.id for e in repo.find_candidates(query)]

    window = (date(2026, 12, 11), date(2026, 12, 13))
    assert ids(CandidateQuery(None, None, *window)) == [_C]
    assert ids(CandidateQuery("u-1", None, *window)) == [_A, _C]
    assert ids(CandidateQuery(None, "https://x/e", *window)) == [_B, _C]
    assert ids(CandidateQuery("nope", "nope", date(2000, 1, 1), date(2000, 1, 1))) == []


def test_the_date_window_uses_the_events_own_time_zone(repo: SqliteEventRepository) -> None:
    # 02:00 UTC on the 13th is still the 12th in New York.
    when = Timed(datetime(2026, 12, 13, 2, 0, tzinfo=UTC), "America/New_York")
    repo.upsert(_event(when=when))
    on_12th = CandidateQuery(None, None, date(2026, 12, 12), date(2026, 12, 12))
    on_13th = CandidateQuery(None, None, date(2026, 12, 13), date(2026, 12, 13))
    assert len(repo.find_candidates(on_12th)) == 1
    assert repo.find_candidates(on_13th) == []


# -- locking ----------------------------------------------------------------------------------


def test_write_lock_is_reentrant_across_runs_and_sits_beside_the_database(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    with ledger_write_lock(db, timeout_s=1):
        assert (tmp_path / "ledger.db.lock").exists()
    with ledger_write_lock(db, timeout_s=1):
        pass


def test_wal_mode_and_foreign_keys_are_on(repo: SqliteEventRepository, db: Path) -> None:
    assert sqlite3.connect(db).execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    with pytest.raises(sqlite3.IntegrityError):  # foreign keys are enforced on our connection
        repo.upsert(_event(_B, mentions=(_mention(_B),), possible_duplicates=(_C,)))


# -- list_all -----------------------------------------------------------------------------------


def test_list_all_returns_every_state_in_date_order(repo: SqliteEventRepository) -> None:
    later = _event(_B, when=AllDay(date(2027, 1, 1)), mentions=(_mention(_B),))
    earlier = _event(_A)
    repo.upsert(later)
    repo.upsert(earlier)
    repo.set_owner_state(_A, ItemState.DISMISSED)
    assert [e.id for e in repo.list_all()] == [_A, _B]
    assert [e.id for e in repo.list_open()] == [_B]


def test_list_all_on_an_empty_database(repo: SqliteEventRepository) -> None:
    assert repo.list_all() == []
