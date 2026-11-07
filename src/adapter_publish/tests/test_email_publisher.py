from __future__ import annotations

import smtplib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self

import pytest

from last_newsletter_adapter_publish.email_publisher import (
    CompositePublisher,
    PublishError,
    SmtpConfig,
    SmtpEmailPublisher,
)
from last_newsletter_core.entities import Cadence, Digest, Theme

if TYPE_CHECKING:
    from email.message import EmailMessage as MimeMessage
    from pathlib import Path

    from last_newsletter_core.ports import DigestPublisher


class FakeSmtp:
    """Records what would have been sent; raises on send when told to."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.sent: list[MimeMessage] = []
        self.logins: list[tuple[str, str]] = []
        self._fail_with = fail_with

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        self.logins.append((user, password))

    def send_message(self, message: MimeMessage) -> None:
        if self._fail_with is not None:
            raise self._fail_with
        self.sent.append(message)


def _config(
    *,
    host: str = "smtp.example.com",
    sender: str = "me@example.com",
    recipient: str = "me@example.com",
) -> SmtpConfig:
    return SmtpConfig(
        host=host,
        port=465,
        username="me@example.com",
        password="pw",
        sender=sender,
        recipient=recipient,
    )


def _body(message: MimeMessage, kind: str) -> str:
    part = message.get_body((kind,))
    assert part is not None
    content = part.get_content()
    assert isinstance(content, str)
    return content


def _digest(*themes: Theme, day: int = 1) -> Digest:
    return Digest(
        period_start=datetime(2026, 11, day, tzinfo=UTC),
        period_end=datetime(2026, 11, day + 7, tzinfo=UTC),
        cadence=Cadence.WEEKLY,
        themes=themes,
        total_messages=len(themes),
        total_sources=len(themes),
    )


def _theme(title: str = "Show", summary: str = "Doors at 8.") -> Theme:
    return Theme(title=title, summary=summary, source_count=1)


def _publisher(tmp_path: Path, smtp: FakeSmtp) -> SmtpEmailPublisher:
    return SmtpEmailPublisher(_config(), sent_dir=tmp_path / "sent", smtp_factory=lambda _c: smtp)


def test_sends_one_multipart_message_with_text_and_html(tmp_path: Path) -> None:
    smtp = FakeSmtp()

    _publisher(tmp_path, smtp).publish(_digest(_theme()))

    assert len(smtp.sent) == 1
    message = smtp.sent[0]
    assert message["Subject"] == "Weekly digest: 2026-11-01 to 2026-11-08"
    assert message["To"] == "me@example.com"
    assert message["From"] == "me@example.com"
    assert message.get_body(("plain",)) is not None
    assert message.get_body(("html",)) is not None
    assert "Doors at 8." in _body(message, "plain")
    assert smtp.logins == [("me@example.com", "pw")]


def test_email_content_is_html_escaped(tmp_path: Path) -> None:
    smtp = FakeSmtp()
    hostile = _theme(title="<script>alert(1)</script>", summary='<img src="http://t.example/x">')

    _publisher(tmp_path, smtp).publish(_digest(hostile))

    html = _body(smtp.sent[0], "html")
    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html


def test_publishing_the_same_period_twice_sends_once(tmp_path: Path) -> None:
    smtp = FakeSmtp()
    publisher = _publisher(tmp_path, smtp)

    publisher.publish(_digest(_theme()))
    publisher.publish(_digest(_theme(), _theme("More")))

    assert len(smtp.sent) == 1


def test_a_different_period_is_sent_again(tmp_path: Path) -> None:
    smtp = FakeSmtp()
    publisher = _publisher(tmp_path, smtp)

    publisher.publish(_digest(_theme(), day=1))
    publisher.publish(_digest(_theme(), day=8))

    assert len(smtp.sent) == 2


def test_a_failed_send_raises_and_is_retried_next_time(tmp_path: Path) -> None:
    failing = FakeSmtp(fail_with=smtplib.SMTPException("550 no"))
    with pytest.raises(PublishError):
        _publisher(tmp_path, failing).publish(_digest(_theme()))

    working = FakeSmtp()
    _publisher(tmp_path, working).publish(_digest(_theme()))

    assert len(working.sent) == 1


def test_a_connection_error_raises_publish_error(tmp_path: Path) -> None:
    def refuse(_config: SmtpConfig) -> FakeSmtp:
        raise ConnectionRefusedError

    publisher = SmtpEmailPublisher(_config(), sent_dir=tmp_path / "sent", smtp_factory=refuse)

    with pytest.raises(PublishError):
        publisher.publish(_digest(_theme()))


def test_an_empty_digest_sends_nothing(tmp_path: Path) -> None:
    smtp = FakeSmtp()

    _publisher(tmp_path, smtp).publish(_digest())

    assert smtp.sent == []


@pytest.mark.parametrize("field", ["sender", "recipient", "host"])
def test_config_rejects_newlines_that_could_inject_headers(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        _config(**{field: "a@example.com\r\nBcc: evil@example.com"})


def test_config_rejects_blank_required_fields() -> None:
    with pytest.raises(ValueError, match="recipient"):
        _config(recipient="  ")


class _Recorder:
    def __init__(self, name: str, log: list[str], *, fail: bool = False) -> None:
        self._name = name
        self._log = log
        self._fail = fail

    def publish(self, digest: Digest) -> None:
        self._log.append(self._name)
        if self._fail:
            msg = "boom"
            raise PublishError(msg)


def test_composite_publishes_in_order() -> None:
    log: list[str] = []
    publishers: list[DigestPublisher] = [_Recorder("a", log), _Recorder("b", log)]

    CompositePublisher(publishers).publish(_digest(_theme()))

    assert log == ["a", "b"]


def test_composite_stops_at_the_first_failure_and_propagates_it() -> None:
    log: list[str] = []
    publishers: list[DigestPublisher] = [
        _Recorder("a", log),
        _Recorder("b", log, fail=True),
        _Recorder("c", log),
    ]

    with pytest.raises(PublishError):
        CompositePublisher(publishers).publish(_digest(_theme()))

    assert log == ["a", "b"]
