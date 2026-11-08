"""The v1 flow end to end on fakes: mail in, extractive digest, emailed at most once."""

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
from last_newsletter_adapter_publish.markdown_publisher import MarkdownPublisher
from last_newsletter_adapter_storage.json_repository import JsonDigestRepository
from last_newsletter_adapter_summarizer.extractive_summarizer import ExtractiveSummarizer
from ranked_digest.entities import Cadence, EmailMessage
from ranked_digest.use_cases.build_digest import BuildDigestRequest, BuildDigestUseCase

if TYPE_CHECKING:
    from email.message import EmailMessage as MimeMessage
    from pathlib import Path

_SINCE = datetime(2026, 11, 1, tzinfo=UTC)
_UNTIL = datetime(2026, 11, 8, tzinfo=UTC)


class _Mailbox:
    def __init__(self, messages: list[EmailMessage]) -> None:
        self._messages = messages

    def fetch_since(self, since: datetime) -> list[EmailMessage]:
        return [m for m in self._messages if m.received_at >= since]


class _Smtp:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[MimeMessage] = []
        self._fail = fail

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        return None

    def send_message(self, message: MimeMessage) -> None:
        if self._fail:
            msg = "550 rejected"
            raise smtplib.SMTPException(msg)
        self.sent.append(message)


def _mail(message_id: str, subject: str) -> EmailMessage:
    return EmailMessage(
        message_id=message_id,
        sender="venue@example.com",
        subject=subject,
        received_at=datetime(2026, 11, 3, tzinfo=UTC),
        body_text="Doors at 8. https://track.example.com/c/1",
        source_label="venue@example.com",
    )


def _use_case(tmp_path: Path, mailbox: _Mailbox, smtp: _Smtp) -> BuildDigestUseCase:
    config = SmtpConfig("h", 465, "u", "p", "me@example.com", "me@example.com")
    email = SmtpEmailPublisher(config, sent_dir=tmp_path / "sent", smtp_factory=lambda _c: smtp)
    return BuildDigestUseCase(
        mailbox,
        ExtractiveSummarizer(),
        CompositePublisher([MarkdownPublisher(tmp_path / "md"), email]),
        JsonDigestRepository(tmp_path / "digests"),
    )


def _request() -> BuildDigestRequest:
    return BuildDigestRequest(since=_SINCE, until=_UNTIL, cadence=Cadence.WEEKLY)


def test_mail_becomes_one_email_and_a_rerun_does_not_send_again(tmp_path: Path) -> None:
    smtp = _Smtp()
    use_case = _use_case(tmp_path, _Mailbox([_mail("m1", "Friday show"), _mail("m2", "Sat")]), smtp)

    first = use_case.execute(_request())
    use_case.execute(_request())

    assert [t.title for t in first.themes] == ["Friday show", "Sat"]
    assert len(smtp.sent) == 1
    assert "track.example.com" not in smtp.sent[0].as_string()


def test_a_failed_send_is_not_saved_and_the_next_run_delivers(tmp_path: Path) -> None:
    mailbox = _Mailbox([_mail("m1", "Friday show")])
    repository = JsonDigestRepository(tmp_path / "digests")

    with pytest.raises(PublishError):
        _use_case(tmp_path, mailbox, _Smtp(fail=True)).execute(_request())
    assert repository.list_recent() == []

    smtp = _Smtp()
    _use_case(tmp_path, mailbox, smtp).execute(_request())

    assert len(smtp.sent) == 1
    assert len(repository.list_recent()) == 1


def test_an_empty_mailbox_sends_nothing(tmp_path: Path) -> None:
    smtp = _Smtp()

    _use_case(tmp_path, _Mailbox([]), smtp).execute(_request())

    assert smtp.sent == []
