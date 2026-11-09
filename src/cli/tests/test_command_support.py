"""The shared ledger session both `process` and `fetch-events` open."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from last_newsletter_adapter_ledger import ledger_write_lock
from last_newsletter_cli.command_support import LEDGER_NAME, ledger_session
from last_newsletter_core.events import (
    AllDay,
    Event,
    EventId,
    EventKind,
    MatchRule,
    Mention,
)

if TYPE_CHECKING:
    from pathlib import Path

_SEEN = datetime(2026, 11, 1, tzinfo=UTC)


def _event(n: int) -> Event:
    event_id = EventId(UUID(int=n))
    return Event(
        id=event_id,
        kind=EventKind.EVENT,
        title=f"Show {n}",
        summary="",
        when=AllDay(date(2026, 12, 1)),
        mentions=(
            Mention(
                message_id=f"m{n}",
                seen_at=_SEEN,
                source="test",
                evidence="e",
                match_rule=MatchRule.NEW,
                cited_event_id=event_id,
            ),
        ),
        first_seen=_SEEN,
        last_seen=_SEEN,
    )


def test_a_real_session_writes_to_the_data_directory(tmp_path: Path) -> None:
    with ledger_session(tmp_path, dry_run=False) as session:
        session.ledger.upsert(_event(1))
        assert session.events_dir == tmp_path / "events"
    assert (tmp_path / "events" / LEDGER_NAME).exists()
    assert session.notes == []


def test_a_dry_run_session_sees_the_real_events_but_saves_nothing(tmp_path: Path) -> None:
    with ledger_session(tmp_path, dry_run=False) as real:
        real.ledger.upsert(_event(1))
    before = sorted(p.name for p in (tmp_path / "events").iterdir())
    with ledger_session(tmp_path, dry_run=True) as dry:
        assert [e.title for e in dry.ledger.list_all()] == ["Show 1"]
        dry.ledger.upsert(_event(2))
        assert dry.events_dir != tmp_path / "events"
    assert dry.notes == ["DRY RUN: nothing below was saved"]
    assert sorted(p.name for p in (tmp_path / "events").iterdir()) == before
    with ledger_session(tmp_path, dry_run=False) as again:
        assert [e.title for e in again.ledger.list_all()] == ["Show 1"]


def test_a_dry_run_on_a_fresh_directory_creates_nothing(tmp_path: Path) -> None:
    with ledger_session(tmp_path, dry_run=True) as dry:
        dry.ledger.upsert(_event(1))
    assert not (tmp_path / "events").exists()


def test_the_write_lock_is_held_for_the_whole_session(tmp_path: Path) -> None:
    with (
        ledger_session(tmp_path, dry_run=False) as session,
        pytest.raises(TimeoutError),
        ledger_write_lock(session.events_dir / LEDGER_NAME, timeout_s=0.2),
    ):
        pass
    with ledger_write_lock(tmp_path / "events" / LEDGER_NAME, timeout_s=0.2):
        pass  # released once the session closed


def test_prepare_runs_on_closed_files_after_the_directory_is_chosen(tmp_path: Path) -> None:
    seen: list[tuple[Path, bool]] = []

    def prepare(events_dir: Path, notes: list[str]) -> None:
        seen.append((events_dir, (events_dir / LEDGER_NAME).exists()))
        notes.append("prepared")

    with ledger_session(tmp_path, dry_run=False, prepare=prepare) as session:
        assert session.notes == ["prepared"]
    assert seen == [(tmp_path / "events", False)]


def test_the_index_is_rebuilt_when_it_is_missing_and_the_session_says_so(tmp_path: Path) -> None:
    with ledger_session(tmp_path, dry_run=False) as first:
        first.ledger.upsert(_event(1))
    with ledger_session(tmp_path, dry_run=True) as dry:
        dry.sync_index()
    assert "rebuilt the similarity index from the ledger" in dry.notes
