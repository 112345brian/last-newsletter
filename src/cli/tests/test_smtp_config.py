from __future__ import annotations

import pytest

from last_newsletter_cli.main import ConfigError, smtp_config_from_env

_FULL = {
    "LAST_NEWSLETTER_SMTP_HOST": "smtp.example.com",
    "LAST_NEWSLETTER_SMTP_USER": "me@example.com",
    "LAST_NEWSLETTER_SMTP_PASSWORD": "pw",
}


def test_minimal_config_defaults_port_sender_recipient_and_ssl() -> None:
    config = smtp_config_from_env(_FULL)

    assert config.host == "smtp.example.com"
    assert config.port == 465
    assert config.sender == "me@example.com"
    assert config.recipient == "me@example.com"
    assert config.use_ssl is True


def test_explicit_values_override_defaults() -> None:
    config = smtp_config_from_env(
        {
            **_FULL,
            "LAST_NEWSLETTER_SMTP_PORT": "587",
            "LAST_NEWSLETTER_SMTP_SSL": "0",
            "LAST_NEWSLETTER_SMTP_FROM": "digest@example.com",
            "LAST_NEWSLETTER_SMTP_TO": "reader@example.com",
        }
    )

    assert (config.port, config.use_ssl) == (587, False)
    assert (config.sender, config.recipient) == ("digest@example.com", "reader@example.com")


def test_missing_host_names_the_variable() -> None:
    environ = {k: v for k, v in _FULL.items() if k != "LAST_NEWSLETTER_SMTP_HOST"}

    with pytest.raises(ConfigError, match="LAST_NEWSLETTER_SMTP_HOST"):
        smtp_config_from_env(environ)


def test_non_numeric_port_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="LAST_NEWSLETTER_SMTP_PORT"):
        smtp_config_from_env({**_FULL, "LAST_NEWSLETTER_SMTP_PORT": "abc"})


def test_invalid_values_surface_as_config_error_not_a_traceback() -> None:
    with pytest.raises(ConfigError, match="recipient"):
        smtp_config_from_env({**_FULL, "LAST_NEWSLETTER_SMTP_TO": "a@x.com\r\nBcc: b@x.com"})
