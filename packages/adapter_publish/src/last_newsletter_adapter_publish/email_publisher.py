"""Concrete DigestPublisher that emails a Digest over SMTP, at most once per period.

Sending is the one irreversible thing this program does, so three rules are enforced here:

- A digest period is sent once. A sent-marker named by `digest_slug` is written after a
  successful send, so a re-run of the same period (same slug) does not email again. If the
  send fails nothing is marked and the next run tries again.
- Failure is loud. Any SMTP or connection error raises `PublishError`; nothing is swallowed, so
  the use case stops before it saves a digest that never went out.
- An empty digest (no themes) is not worth an email and is skipped without a marker.

Everything taken from an email is HTML-escaped by `render_html`, and header values come only
from configuration, which rejects line breaks so a value cannot inject headers.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from typing import TYPE_CHECKING, Protocol, Self

from last_newsletter_adapter_publish.render import digest_heading, render_html, render_markdown
from last_newsletter_core.entities import digest_slug

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from last_newsletter_core.entities import Digest
    from last_newsletter_core.ports import DigestPublisher


class PublishError(RuntimeError):
    """A digest could not be delivered. Raised, never returned, so it cannot be ignored."""


def _no_line_breaks(name: str, value: str) -> None:
    if not value.strip():
        msg = f"{name} must not be blank"
        raise ValueError(msg)
    if "\r" in value or "\n" in value:
        msg = f"{name} must not contain line breaks"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    sender: str
    recipient: str
    use_ssl: bool = True

    def __post_init__(self) -> None:
        _no_line_breaks("host", self.host)
        _no_line_breaks("sender", self.sender)
        _no_line_breaks("recipient", self.recipient)
        if bool(self.username) != bool(self.password):
            msg = "username and password must both be set or both be empty"
            raise ValueError(msg)


class SmtpSession(Protocol):
    def __enter__(self) -> Self: ...
    def __exit__(self, *exc: object) -> None: ...
    def login(self, user: str, password: str) -> None: ...
    def send_message(self, message: MimeMessage) -> None: ...


class _SmtpConnection:
    """The real connection, exposed as exactly the small surface the publisher uses."""

    def __init__(self, config: SmtpConfig) -> None:
        context = ssl.create_default_context()
        if config.use_ssl:
            self._smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                config.host, config.port, context=context, timeout=30
            )
        else:
            self._smtp = smtplib.SMTP(config.host, config.port, timeout=30)
            self._smtp.starttls(context=context)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self._smtp.quit()

    def login(self, user: str, password: str) -> None:
        self._smtp.login(user, password)

    def send_message(self, message: MimeMessage) -> None:
        self._smtp.send_message(message)


def _open_smtp(config: SmtpConfig) -> SmtpSession:
    return _SmtpConnection(config)


class SmtpEmailPublisher:
    """Implements last_newsletter_core.ports.DigestPublisher."""

    def __init__(
        self,
        config: SmtpConfig,
        *,
        sent_dir: Path,
        smtp_factory: Callable[[SmtpConfig], SmtpSession] = _open_smtp,
    ) -> None:
        self._config = config
        self._sent_dir = sent_dir
        self._smtp_factory = smtp_factory

    def _marker(self, digest: Digest) -> Path:
        return self._sent_dir / f"{digest_slug(digest)}.sent"

    def _message(self, digest: Digest) -> MimeMessage:
        message = MimeMessage()
        message["Subject"] = digest_heading(digest)
        message["From"] = self._config.sender
        message["To"] = self._config.recipient
        message.set_content(render_markdown(digest))
        message.add_alternative(render_html(digest), subtype="html")
        return message

    def publish(self, digest: Digest) -> None:
        if not digest.themes:
            return
        marker = self._marker(digest)
        if marker.exists():
            return
        message = self._message(digest)
        try:
            with self._smtp_factory(self._config) as smtp:
                if self._config.username:
                    smtp.login(self._config.username, self._config.password)
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as error:
            msg = f"could not send digest {digest_slug(digest)}: {error}"
            raise PublishError(msg) from error
        self._sent_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(self._config.recipient)


class CompositePublisher:
    """Publishes to several publishers in order and stops at the first failure."""

    def __init__(self, publishers: Sequence[DigestPublisher]) -> None:
        self._publishers = tuple(publishers)

    def publish(self, digest: Digest) -> None:
        for publisher in self._publishers:
            publisher.publish(digest)
