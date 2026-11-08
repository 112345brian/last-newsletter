from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from last_newsletter_adapter_ledger import SqliteEventRepository
from last_newsletter_adapter_semantic import HashedNgramIndex
from last_newsletter_adapter_storage import JsonEventRepository
from last_newsletter_cli.ledger_import import import_json_ledger
from last_newsletter_cli.similarity import sync_index
from last_newsletter_core.events import (
    AllDay,
    Event,
    EventId,
    EventKind,
    MatchRule,
    Mention,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_T = datetime(2026, 11, 5, 12, tzinfo=UTC)
_A = EventId(UUID(int=1))
_B = EventId(UUID(int=2))


def _event(event_id: EventId, title: str, **overrides: object) -> Event:
    mention = Mention(
        message_id=f"<{event_id.int}@x>",
        seen_at=_T,
        source="sender",
        evidence=f"{title} Sat Dec 12",
        match_rule=MatchRule.NEW,
        cited_event_id=event_id,
    )
    return replace(
        Event(
            id=event_id,
            kind=EventKind.EVENT,
            title=title,
            summary="",
            when=AllDay(date(2026, 12, 12)),
            mentions=(mention,),
            first_seen=_T,
            last_seen=_T,
        ),
        **overrides,
    )


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[SqliteEventRepository]:
    with SqliteEventRepository(tmp_path / "ledger.sqlite") as repo:
        yield repo


def _seed_json(path: Path, *events: Event) -> None:
    repo = JsonEventRepository(path)
    for event in events:
        repo.upsert(event)


def test_import_moves_every_event_with_its_uuid_mentions_and_links(
    tmp_path: Path, ledger: SqliteEventRepository
) -> None:
    path = tmp_path / "events.json"
    first = _event(_A, "Band at Venue")
    second = _event(_B, "Band Live", possible_duplicates=(_A,))
    _seed_json(path, second, first)  # the linked event is listed before its target

    assert import_json_ledger(path, ledger) == 2

    assert ledger.get(_A) == first
    assert ledger.get(_B) == second
    assert not path.exists()
    assert path.with_name("events.json.imported").exists()  # kept as a backup, never deleted


def test_import_is_one_time(tmp_path: Path, ledger: SqliteEventRepository) -> None:
    path = tmp_path / "events.json"
    _seed_json(path, _event(_A, "Band at Venue"))
    assert import_json_ledger(path, ledger) == 1
    assert import_json_ledger(path, ledger) == 0
    assert [e.id for e in ledger.list_all()] == [_A]


def test_import_without_a_json_file_does_nothing(
    tmp_path: Path, ledger: SqliteEventRepository
) -> None:
    assert import_json_ledger(tmp_path / "events.json", ledger) == 0
    assert ledger.list_all() == []


def test_import_never_overwrites_an_event_the_ledger_already_has(
    tmp_path: Path, ledger: SqliteEventRepository
) -> None:
    ledger.upsert(_event(_A, "Newer title"))
    path = tmp_path / "events.json"
    _seed_json(path, _event(_A, "Older title"), _event(_B, "Other"))

    assert import_json_ledger(path, ledger) == 1

    kept = ledger.get(_A)
    assert kept is not None
    assert kept.title == "Newer title"
    assert ledger.get(_B) is not None


def test_corrupt_json_raises_and_is_left_in_place(
    tmp_path: Path, ledger: SqliteEventRepository
) -> None:
    path = tmp_path / "events.json"
    path.write_text("{not json")
    with pytest.raises(ValueError, match=r"Expecting|property"):
        import_json_ledger(path, ledger)
    assert path.exists()
    assert ledger.list_all() == []


def test_index_is_rebuilt_when_missing_or_out_of_sync(tmp_path: Path) -> None:
    events = [_event(_A, "Band at Venue"), _event(_B, "Quiz Night")]
    index = HashedNgramIndex(tmp_path / "similar.sqlite")
    assert sync_index(index, events) is True  # missing: built from the ledger
    assert index.ids() == {str(_A), str(_B)}
    assert sync_index(index, events) is False  # in sync: left alone
    assert sync_index(index, events[:1]) is True  # ledger lost an event: stale entry dropped
    assert index.ids() == {str(_A)}
    index.close()
