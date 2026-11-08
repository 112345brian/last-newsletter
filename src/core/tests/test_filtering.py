from __future__ import annotations

from datetime import UTC, datetime

import pytest

from last_newsletter_core.filtering import FilterRule
from ranked_digest.entities import EmailMessage


def _message(
    sender: str = "newsletter@example.com", subject: str = "This week in AI"
) -> EmailMessage:
    return EmailMessage(
        message_id="m1",
        sender=sender,
        subject=subject,
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        body_text="body",
    )


def test_rule_with_neither_signal_set_raises() -> None:
    with pytest.raises(ValueError, match="sender_domains, subject_phrases, or both"):
        FilterRule(name="useless")


def test_sender_domain_only_matches_any_subject_from_that_domain() -> None:
    rule = FilterRule(name="r", sender_domains=("google.com",))

    assert rule.matches(_message(sender="no-reply@google.com", subject="anything at all"))
    assert not rule.matches(_message(sender="newsletter@example.com"))


def test_subject_phrase_only_matches_any_sender_with_that_subject() -> None:
    rule = FilterRule(name="r", subject_phrases=("security alert",))

    assert rule.matches(_message(subject="Security Alert"))
    assert not rule.matches(_message(subject="This week in AI"))


def test_both_signals_require_sender_domain_and_subject_phrase_together() -> None:
    rule = FilterRule(name="r", sender_domains=("google.com",), subject_phrases=("security alert",))

    assert rule.matches(_message(sender="no-reply@google.com", subject="Security alert"))
    assert not rule.matches(_message(sender="newsletter@example.com", subject="Security alert"))
    assert not rule.matches(_message(sender="no-reply@google.com", subject="This week in AI"))


def test_a_newsletter_that_mentions_the_phrase_but_is_from_a_different_domain_is_not_matched() -> (
    None
):
    """Defensive case from the task: a real newsletter discussing "security" in passing must
    not be dropped just because its subject happens to contain a filtered phrase."""
    rule = FilterRule(
        name="google-account-security",
        sender_domains=("google.com", "accounts.google.com"),
        subject_phrases=("security alert",),
    )

    assert not rule.matches(
        _message(sender="newsletter@securityweekly.example.com", subject="Security Alert Roundup")
    )


def test_sender_domain_match_is_case_insensitive_and_ignores_display_name() -> None:
    rule = FilterRule(name="r", sender_domains=("google.com",))

    assert rule.matches(_message(sender="Google <no-reply@GOOGLE.COM>"))
