from datetime import UTC, datetime
from pathlib import Path

from last_newsletter_adapter_storage.json_repository import JsonDigestRepository
from last_newsletter_core.entities import Cadence, Digest, Theme


def _digest() -> Digest:
    return Digest(
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 1, 8, tzinfo=UTC),
        cadence=Cadence.WEEKLY,
        themes=(
            Theme(title="AI agents", summary="s", source_count=4, source_message_ids=("a", "b")),
        ),
        total_messages=47,
        total_sources=23,
    )


def test_save_then_get_round_trips(tmp_path: Path) -> None:
    repo = JsonDigestRepository(tmp_path)
    digest = _digest()

    slug = repo.save(digest)
    loaded = repo.get(slug)

    assert loaded == digest


def test_get_missing_slug_returns_none(tmp_path: Path) -> None:
    repo = JsonDigestRepository(tmp_path)

    assert repo.get("does-not-exist") is None


def test_list_recent_returns_newest_first(tmp_path: Path) -> None:
    repo = JsonDigestRepository(tmp_path)
    older = Digest(
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 1, 8, tzinfo=UTC),
        cadence=Cadence.WEEKLY,
        themes=(),
        total_messages=0,
        total_sources=0,
    )
    newer = Digest(
        period_start=datetime(2026, 1, 8, tzinfo=UTC),
        period_end=datetime(2026, 1, 15, tzinfo=UTC),
        cadence=Cadence.WEEKLY,
        themes=(),
        total_messages=0,
        total_sources=0,
    )
    repo.save(older)
    repo.save(newer)

    recent = repo.list_recent()

    assert [digest for _, digest in recent] == [newer, older]
