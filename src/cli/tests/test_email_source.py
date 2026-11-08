from __future__ import annotations

from typing import TYPE_CHECKING

from last_newsletter_adapter_email.filtered_source import FilteredEmailSource
from last_newsletter_adapter_email.imap_source import ImapEmailSource
from last_newsletter_cli.main import _email_source

if TYPE_CHECKING:
    import pytest

_IMAP_ENV = {
    "LAST_NEWSLETTER_IMAP_HOST": "imap.example.com",
    "LAST_NEWSLETTER_IMAP_USER": "user",
    "LAST_NEWSLETTER_IMAP_PASSWORD": "pw",
}


def _set_imap_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _IMAP_ENV.items():
        monkeypatch.setenv(name, value)


def test_default_wraps_the_real_source_with_the_default_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_imap_env(monkeypatch)
    monkeypatch.delenv("LAST_NEWSLETTER_DISABLE_DEFAULT_FILTERS", raising=False)

    source = _email_source()

    assert isinstance(source, FilteredEmailSource)


def test_disable_flag_returns_the_unwrapped_source(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_imap_env(monkeypatch)
    monkeypatch.setenv("LAST_NEWSLETTER_DISABLE_DEFAULT_FILTERS", "1")

    source = _email_source()

    assert isinstance(source, ImapEmailSource)
