"""Each rule must catch the real Google/Gmail noise it was written for, and must not catch a
genuine newsletter that shares surface similarity with it."""

from __future__ import annotations

from datetime import UTC, datetime

from last_newsletter_core.default_filters import DEFAULT_FILTERS
from last_newsletter_core.entities import EmailMessage


def _message(sender: str, subject: str) -> EmailMessage:
    return EmailMessage(
        message_id="m1",
        sender=sender,
        subject=subject,
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        body_text="body",
    )


def _dropped(message: EmailMessage) -> bool:
    return any(rule.matches(message) for rule in DEFAULT_FILTERS)


def test_security_alert_from_google_is_dropped() -> None:
    assert _dropped(_message("Google <no-reply@accounts.google.com>", "Security alert"))


def test_2_step_verification_turned_on_is_dropped() -> None:
    assert _dropped(
        _message("Google <no-reply@accounts.google.com>", "2-Step Verification turned on")
    )


def test_gmail_forwarding_confirmation_is_dropped() -> None:
    assert _dropped(
        _message(
            "Gmail Team <forwarding-noreply@google.com>",
            "Gmail Forwarding Confirmation - Receive Mail from someone@example.com",
        )
    )


def test_free_copilot_access_promo_is_dropped() -> None:
    assert _dropped(
        _message("Google Workspace <no-reply@google.com>", "Your free Copilot access is ready")
    )


def test_welcome_to_google_on_mac_os_is_dropped() -> None:
    assert _dropped(_message("Google <no-reply@google.com>", "Welcome to Google on your Mac OS"))


def test_a_newsletter_about_account_security_from_a_real_sender_is_not_dropped() -> None:
    assert not _dropped(
        _message("Krebs on Security <newsletter@krebsonsecurity.com>", "Security Alert: new breach")
    )


def test_a_newsletter_welcoming_new_subscribers_is_not_dropped() -> None:
    assert not _dropped(
        _message("Some Newsletter <hello@example.com>", "Welcome to Google I/O coverage")
    )


def test_an_ordinary_newsletter_is_not_dropped() -> None:
    assert not _dropped(_message("newsletter@example.com", "This week in AI"))
