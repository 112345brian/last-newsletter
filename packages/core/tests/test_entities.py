from datetime import UTC, datetime

from last_newsletter_core.entities import Cadence, Digest, digest_slug


def test_digest_slug_includes_period_start_and_cadence() -> None:
    digest = Digest(
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 1, 8, tzinfo=UTC),
        cadence=Cadence.WEEKLY,
        themes=(),
        total_messages=0,
        total_sources=0,
    )

    assert digest_slug(digest) == "2026-01-01T000000_weekly"


def test_digest_slug_is_the_same_rule_every_adapter_must_share() -> None:
    """adapter_storage and adapter_publish both name a digest's file by this -- a change here
    is a change to the on-disk naming scheme everywhere, by construction, not by two adapters
    happening to agree."""
    digest = Digest(
        period_start=datetime(2026, 3, 2, 9, tzinfo=UTC),
        period_end=datetime(2026, 3, 3, tzinfo=UTC),
        cadence=Cadence.DAILY,
        themes=(),
        total_messages=0,
        total_sources=0,
    )

    assert digest_slug(digest) == "2026-03-02T090000_daily"
