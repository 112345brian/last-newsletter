"""Default noise rules for the intended setup: forwarding newsletters to (or IMAP-connecting)
a dedicated Gmail mailbox (see README.md). That mailbox's inbox also fills with Google's own
account-setup and security mail, which is not a newsletter and has no business in a digest.

Each rule pairs a real Google/Gmail notification sender domain with the specific subject text
that notification uses, so a newsletter that happens to mention "security" or "welcome" in
passing is not dropped -- see FilterRule's docstring for why both signals are required
together. Extend this list by appending another FilterRule; nothing else needs to change.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from last_newsletter_core.filtering import FilterRule

DEFAULT_FILTERS: tuple[FilterRule, ...] = (
    FilterRule(
        name="google-account-security",
        sender_domains=("google.com", "accounts.google.com"),
        subject_phrases=(
            "security alert",
            "2-step verification turned on",
            "new sign-in",
        ),
    ),
    FilterRule(
        name="gmail-forwarding-confirmation",
        sender_domains=("gmail.com", "google.com"),
        subject_phrases=("gmail forwarding confirmation",),
    ),
    FilterRule(
        name="google-account-welcome-and-promo",
        sender_domains=("google.com", "workspace.google.com"),
        subject_phrases=(
            "welcome to google",
            "your free copilot access is ready",
        ),
    ),
)
