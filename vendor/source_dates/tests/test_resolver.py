"""Resolving a source-reported date against its observation time."""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from source_dates.resolver import first_iso_date, resolve_date

OBSERVED = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(("value", "expected"), [
    ("2026-09-01T10:00:00Z", "2026-09-01"),
    ("Posted 2 days ago", "2026-09-26"),
    ("Reposted 3 days ago", "2026-09-25"),
    ("30+ days ago", "2026-08-29"),
    ("Just posted", "2026-09-28"),
    ("New", "2026-09-28"),
    ("", ""),
    ("   ", ""),
    (None, ""),
    (20260901, ""),
    ("not a date at all", ""),
])
def test_a_source_value_resolves_against_the_observation_time(value, expected):
    assert resolve_date(value, observed_at=OBSERVED) == expected


def test_a_naive_observation_time_is_refused():
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_date("2 days ago", observed_at=datetime(2026, 9, 28))


def test_first_iso_date_reads_a_date_out_of_prose_and_skips_impossible_ones():
    assert first_iso_date("It closes 2026-13-45, or really on 2026-10-02.") == date(2026, 10, 2)
    assert first_iso_date("no date") is None
    assert first_iso_date("") is None
