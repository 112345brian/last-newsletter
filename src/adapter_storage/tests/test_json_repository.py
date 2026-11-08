from datetime import UTC, date, datetime
from pathlib import Path

from last_newsletter_adapter_storage.json_repository import JsonDigestRepository
from ranked_digest.entities import Cadence, Digest, Theme


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


def test_round_trip_preserves_every_continuity_and_personalization_field(tmp_path: Path) -> None:
    """A field added to Theme and forgotten here would silently vanish on the next
    `build` -- carry-forward and personalization both depend on this repository, not
    just on the in-memory object, since BuildDigestUseCase reloads prior themes from it."""
    theme = Theme(
        title="Ongoing saga",
        summary="s",
        source_count=3,
        source_message_ids=("a", "b"),
        theme_key="ongoing-saga",
        relevant_until=date(2026, 2, 1),
        first_seen=date(2026, 1, 1),
        streak=4,
        carried_forward=True,
        personal_weight=3.5,
    )
    digest = Digest(
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 1, 8, tzinfo=UTC),
        cadence=Cadence.WEEKLY,
        themes=(theme,),
        total_messages=1,
        total_sources=1,
    )
    repo = JsonDigestRepository(tmp_path)

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


def test_get_rejects_slugs_that_could_escape_the_digest_directory(tmp_path: Path) -> None:
    """A slug is an opaque token from `save`/`list_recent`; anything else (a URL segment
    forwarded by adapter_web, say) must never be turned into a filesystem path."""
    digests_dir = tmp_path / "digests"
    outside = tmp_path / "secret.json"
    outside.write_text("{}")
    repo = JsonDigestRepository(digests_dir)

    for hostile in ("../secret", "..", ".", "", "a/b", "a\\b", "a\0b", "/etc/passwd", str(outside)):
        assert repo.get(hostile) is None, hostile
