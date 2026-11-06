"""Tracking-parameter and trailing-slash normalization of a URL (characterized before it moved out of state.job_identity)."""
from __future__ import annotations

import pytest

from identity_dedupe.url_normalize import normalize_url

CASES = [
    ("https://Example.com/Jobs/123/?utm_source=x&utm_medium=y", "https://example.com/Jobs/123"),
    ("https://example.com/jobs/123?ref=abc&id=9", "https://example.com/jobs/123?id=9"),
    ("https://example.com/jobs?source=li&tracking=1&q=a&q=b", "https://example.com/jobs?q=a&q=b"),
    ("HTTPS://EXAMPLE.COM/a/b///", "https://example.com/a/b"),
    ("https://example.com/a#frag", "https://example.com/a"),
    ("https://example.com/a;p=1?x=1", "https://example.com/a;p=1?x=1"),
    ("not a url/ ", "not a url/ "),
    ("", ""),
]


@pytest.mark.parametrize(("url", "expected"), CASES)
def test_a_url_loses_tracking_params_fragment_and_trailing_slashes(url, expected):
    assert normalize_url(url) == expected


def test_a_param_starting_with_a_tracking_prefix_is_dropped_even_when_it_is_a_real_word():
    # Pinned as-is: "referral" starts with "ref", so it goes too; "sourcing" does not start with "source".
    assert normalize_url("https://e.com/a?referral=1&sourcing=2&keep=3") == "https://e.com/a?sourcing=2&keep=3"
