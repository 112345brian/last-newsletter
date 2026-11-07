from __future__ import annotations

from datetime import UTC, datetime

from last_newsletter_cli.main import build_window
from last_newsletter_core.entities import Cadence

_NOW = datetime(2026, 11, 7, 14, 30, 0, tzinfo=UTC)


def test_default_daily_window_is_aligned_to_midnight_not_now() -> None:
    since, until = build_window(Cadence.DAILY, now=_NOW)

    assert until == datetime(2026, 11, 7, tzinfo=UTC)
    assert since == datetime(2026, 11, 6, tzinfo=UTC)


def test_default_weekly_window_is_aligned_to_midnight_not_now() -> None:
    since, until = build_window(Cadence.WEEKLY, now=_NOW)

    assert until == datetime(2026, 11, 7, tzinfo=UTC)
    assert since == datetime(2026, 10, 31, tzinfo=UTC)


def test_force_extends_until_to_right_now() -> None:
    since, until = build_window(Cadence.DAILY, now=_NOW, force=True)

    assert until == _NOW
    assert since == datetime(2026, 11, 6, 14, 30, 0, tzinfo=UTC)


def test_force_includes_a_message_from_earlier_today() -> None:
    _, until = build_window(Cadence.DAILY, now=_NOW, force=True)
    message_received_at = datetime(2026, 11, 7, 10, 0, 0, tzinfo=UTC)

    assert message_received_at < until


def test_without_force_a_message_from_earlier_today_is_excluded() -> None:
    _, until = build_window(Cadence.DAILY, now=_NOW, force=False)
    message_received_at = datetime(2026, 11, 7, 10, 0, 0, tzinfo=UTC)

    assert message_received_at >= until
