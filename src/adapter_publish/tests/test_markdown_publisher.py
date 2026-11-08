from datetime import UTC, date, datetime
from pathlib import Path

from last_newsletter_adapter_publish.markdown_publisher import MarkdownPublisher
from ranked_digest.entities import Cadence, Digest, Theme


def _digest(themes: tuple[Theme, ...] = ()) -> Digest:
    return Digest(
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 1, 8, tzinfo=UTC),
        cadence=Cadence.WEEKLY,
        themes=themes,
        total_messages=47,
        total_sources=23,
    )


def test_publish_creates_output_dir_if_missing(tmp_path: Path) -> None:
    output_dir = tmp_path / "digests"
    MarkdownPublisher(output_dir)

    assert output_dir.is_dir()


def test_publish_writes_a_file_named_by_period_and_cadence(tmp_path: Path) -> None:
    publisher = MarkdownPublisher(tmp_path)

    publisher.publish(_digest())

    assert (tmp_path / "2026-01-01T000000_weekly.md").is_file()


def test_rendered_markdown_includes_header_and_counts(tmp_path: Path) -> None:
    publisher = MarkdownPublisher(tmp_path)

    publisher.publish(_digest())

    content = (tmp_path / "2026-01-01T000000_weekly.md").read_text()
    assert "Weekly digest: 2026-01-01 to 2026-01-08" in content
    assert "47 messages from 23 sources." in content


def test_rendered_markdown_with_no_themes_says_so(tmp_path: Path) -> None:
    publisher = MarkdownPublisher(tmp_path)

    publisher.publish(_digest())

    content = (tmp_path / "2026-01-01T000000_weekly.md").read_text()
    assert "No themes this period." in content


def test_theme_section_includes_title_count_and_summary(tmp_path: Path) -> None:
    theme = Theme(title="AI agents", summary="Four sources covered this.", source_count=4)
    publisher = MarkdownPublisher(tmp_path)

    publisher.publish(_digest((theme,)))

    content = (tmp_path / "2026-01-01T000000_weekly.md").read_text()
    assert "## AI agents (4 sources)" in content
    assert "Four sources covered this." in content


def test_theme_section_mentions_relevant_until_when_set(tmp_path: Path) -> None:
    theme = Theme(title="Conference", summary="s", source_count=1, relevant_until=date(2026, 2, 1))
    publisher = MarkdownPublisher(tmp_path)

    publisher.publish(_digest((theme,)))

    content = (tmp_path / "2026-01-01T000000_weekly.md").read_text()
    assert "Relevant until 2026-02-01" in content


def test_theme_section_mentions_streak_only_when_greater_than_one(tmp_path: Path) -> None:
    recurring = Theme(title="Saga", summary="s", source_count=1, streak=3)
    fresh = Theme(title="Fresh", summary="s", source_count=1, streak=1)
    publisher = MarkdownPublisher(tmp_path)

    publisher.publish(_digest((recurring, fresh)))

    content = (tmp_path / "2026-01-01T000000_weekly.md").read_text()
    assert "Recurring for 3 periods in a row." in content
    assert "## Fresh" in content
    assert "Recurring for 1" not in content
