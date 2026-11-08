from __future__ import annotations

from datetime import UTC, datetime

from last_newsletter_cli.build_report import BuildFacts, describe_build
from ranked_digest.entities import Cadence, Digest

_SINCE = datetime(2026, 10, 31, tzinfo=UTC)
_UNTIL = datetime(2026, 11, 7, tzinfo=UTC)
_NEWEST = datetime(2026, 11, 6, 9, tzinfo=UTC)


def _digest(messages: int, sources: int = 1) -> Digest:
    return Digest(
        period_start=_SINCE,
        period_end=_UNTIL,
        cadence=Cadence.WEEKLY,
        themes=(),
        total_messages=messages,
        total_sources=sources,
    )


def _facts(
    *,
    replaced: bool = False,
    force: bool = False,
    raw_total: int = 16,
    raw_newest: datetime | None = _NEWEST,
) -> BuildFacts:
    return BuildFacts(
        slug="2026-10-31T000000_weekly",
        replaced=replaced,
        force=force,
        raw_total=raw_total,
        raw_newest=raw_newest,
        output_dir="/data/markdown",
    )


def test_the_window_and_the_outcome_are_always_stated() -> None:
    text = "\n".join(describe_build(_digest(5, 2), _facts()))
    assert "2026-10-31 00:00 UTC" in text
    assert "2026-11-07 00:00 UTC" in text
    assert "weekly" in text
    assert "5 message(s) from 2 source(s)" in text
    assert "2026-10-31T000000_weekly" in text


def test_a_rebuilt_window_says_it_replaced_the_earlier_digest_and_what_force_does() -> None:
    text = "\n".join(describe_build(_digest(5), _facts(replaced=True)))
    assert "replaced" in text
    assert "no new period" in text
    assert "--force" in text
    assert "today" in text


def test_an_empty_window_says_why_nothing_was_summarised() -> None:
    text = "\n".join(describe_build(_digest(0, 0), _facts(raw_newest=_SINCE)))
    assert "no raw message was received inside the window" in text
    assert "16 message(s)" in text
    assert "fetch" in text


def test_an_empty_raw_store_points_at_fetch() -> None:
    text = "\n".join(describe_build(_digest(0, 0), _facts(raw_total=0, raw_newest=None)))
    assert "raw store is empty" in text
    assert "fetch" in text


def test_force_is_described_as_ending_the_window_now() -> None:
    text = "\n".join(describe_build(_digest(1), _facts(force=True)))
    assert "--force" in text
    assert "ends at this moment" in text
