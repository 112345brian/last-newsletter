"""Concrete EmailSource: connects to a mailbox over IMAP and maps messages to core entities.

Credentials live in environment variables, never in code or config committed to the repo.
Read-only throughout (`select_folder(..., readonly=True)`, SEARCH/FETCH only) — this adapter
never adds/removes flags or deletes anything in the mailbox it's pointed at.

Uses `imapclient` (parsed responses, real exceptions) instead of the stdlib `imaplib` directly
(string-keyed, mostly-unparsed responses, return-code checking instead of exceptions), and
`html2text` for HTML-only newsletters instead of a hand-rolled tag-stripper, which among other
things correctly drops <script>/<style> *content*, not just the surrounding tags.
"""

from __future__ import annotations

import email
from dataclasses import dataclass
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Protocol, Self, cast

import html2text
from imapclient import IMAPClient

from last_newsletter_core.entities import EmailMessage

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from email.message import Message
    from types import TracebackType


class _ImapConnection(Protocol):
    """The subset of IMAPClient's interface this adapter needs — small enough to fake in tests
    instead of standing up a real mailbox or mocking imapclient itself."""

    def login(self, username: str, password: str) -> bytes: ...
    def select_folder(self, folder: str, *, readonly: bool) -> dict[bytes, object]: ...
    def search(self, criteria: list[object]) -> list[int]: ...
    def fetch(self, messages: list[int], data: list[str]) -> dict[int, dict[bytes, bytes]]: ...
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
        /,
    ) -> bool | None: ...


_html_converter = html2text.HTML2Text()
_html_converter.ignore_images = True
_html_converter.ignore_tables = False


@dataclass(frozen=True, slots=True)
class ImapConfig:
    host: str
    username: str
    password: str
    mailbox: str = "INBOX"


def _decode_header_value(raw: str | None) -> str:
    if not bool(raw):
        return ""
    chunks: list[str] = []
    for part, charset in decode_header(raw):
        chunks.append(
            part.decode(charset or "utf-8", errors="replace")
            if isinstance(part, bytes)
            else str(part)
        )
    return "".join(chunks)


def _body_text(msg: Message) -> str:
    plain: str | None = None
    html: str | None = None
    for part in msg.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        charset = part.get_content_charset() or "utf-8"
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        decoded = payload.decode(charset, errors="replace")
        if part.get_content_type() == "text/plain" and plain is None:
            plain = decoded
        elif part.get_content_type() == "text/html" and html is None:
            html = decoded
    if plain is not None:
        return plain.strip()
    if html is not None:
        return _html_converter.handle(html).strip()
    return ""


def _to_email_message(raw: bytes) -> EmailMessage | None:
    msg = email.message_from_bytes(raw)
    date_header = msg.get("Date")
    if not bool(date_header):
        return None
    try:
        received_at = parsedate_to_datetime(date_header)
    except (TypeError, ValueError):
        return None
    if received_at.tzinfo is None:
        # A malformed Date header with no offset -- can't be compared against an aware `since`
        # (and a time without a zone isn't trustworthy for date-based ranking anyway).
        return None
    sender = _decode_header_value(msg.get("From"))
    return EmailMessage(
        message_id=msg.get("Message-ID", ""),
        sender=sender,
        subject=_decode_header_value(msg.get("Subject")),
        received_at=received_at,
        body_text=_body_text(msg),
        source_label=sender,
    )


def _default_connect(host: str) -> _ImapConnection:
    # imapclient ships no type stubs, so IMAPClient.__exit__'s return type is Unknown to ty --
    # it structurally satisfies _ImapConnection (confirmed: Unknown is *assignable*), just not
    # provably a strict subtype in a return position. cast() says so explicitly, once, here.
    return cast("_ImapConnection", IMAPClient(host))


class ImapEmailSource:
    """Implements last_newsletter_core.ports.EmailSource.

    `source_label` on each returned message is the sender address: distinct senders are what
    `core`'s `total_sources` and cross-source theme ranking count as distinct newsletters.
    """

    def __init__(
        self,
        config: ImapConfig,
        *,
        connect: Callable[[str], _ImapConnection] = _default_connect,
    ) -> None:
        """`connect` defaults to a real IMAPClient connection; tests pass a fake instead."""
        self._config = config
        self._connect = connect

    def fetch_since(self, since: datetime) -> list[EmailMessage]:
        config = self._config
        with self._connect(config.host) as conn:
            conn.login(config.username, config.password)
            conn.select_folder(config.mailbox, readonly=True)
            # IMAP's SEARCH SINCE is day-granular, not a precise timestamp -- it can include
            # messages from earlier the same day as `since`. Filtered again below by received_at.
            message_ids = conn.search(["SINCE", since.date()])
            if not message_ids:
                return []
            response = conn.fetch(message_ids, ["RFC822"])
            messages: list[EmailMessage] = []
            for data in response.values():
                raw = data.get(b"RFC822")
                if raw is None:
                    continue
                message = _to_email_message(raw)
                if message is not None and message.received_at >= since:
                    messages.append(message)
            return messages
