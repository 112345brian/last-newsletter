from __future__ import annotations

from datetime import UTC, datetime

from last_newsletter_adapter_email.filtered_source import FilteredEmailSource
from last_newsletter_core.entities import EmailMessage
from last_newsletter_core.filtering import FilterRule

_SINCE = datetime(2026, 1, 1, tzinfo=UTC)


class _FakeSource:
    def __init__(self, messages: list[EmailMessage]) -> None:
        self._messages = messages

    def fetch_since(self, since: datetime) -> list[EmailMessage]:
        del since
        return self._messages


def _message(message_id: str, sender: str, subject: str) -> EmailMessage:
    return EmailMessage(
        message_id=message_id,
        sender=sender,
        subject=subject,
        received_at=_SINCE,
        body_text="body",
    )


def test_zero_filters_returns_every_message_unchanged() -> None:
    messages = [_message("m1", "a@example.com", "A"), _message("m2", "b@example.com", "B")]
    source = FilteredEmailSource(_FakeSource(messages))

    assert source.fetch_since(_SINCE) == messages


def test_one_filter_drops_only_the_matching_message() -> None:
    kept = _message("m1", "newsletter@example.com", "This week in AI")
    dropped = _message("m2", "no-reply@google.com", "Security alert")
    rule = FilterRule(name="google", sender_domains=("google.com",))
    source = FilteredEmailSource(_FakeSource([kept, dropped]), [rule])

    assert source.fetch_since(_SINCE) == [kept]


def test_multiple_filters_drop_a_message_matched_by_any_one_of_them() -> None:
    kept = _message("m1", "newsletter@example.com", "This week in AI")
    dropped_by_first = _message("m2", "no-reply@google.com", "anything")
    dropped_by_second = _message("m3", "someone@example.com", "2-step verification turned on")
    rules = [
        FilterRule(name="google-sender", sender_domains=("google.com",)),
        FilterRule(name="2sv-subject", subject_phrases=("2-step verification turned on",)),
    ]
    source = FilteredEmailSource(_FakeSource([kept, dropped_by_first, dropped_by_second]), rules)

    assert source.fetch_since(_SINCE) == [kept]
