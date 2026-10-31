from __future__ import annotations

from datetime import UTC, datetime
from email.message import EmailMessage as StdlibEmailMessage
from typing import Self

from last_newsletter_adapter_email.imap_source import ImapConfig, ImapEmailSource


def _raw_message(
    *,
    sender: str = "newsletter@example.com",
    subject: str = "This week in AI",
    date: datetime | None = None,
    body: str = "Plain text body.",
    html_body: str | None = None,
    include_date: bool = True,
) -> bytes:
    msg = StdlibEmailMessage()
    msg["From"] = sender
    msg["Subject"] = subject
    msg["Message-ID"] = "<abc123@example.com>"
    if include_date:
        msg["Date"] = (date or datetime(2026, 1, 5, tzinfo=UTC)).strftime(
            "%a, %d %b %Y %H:%M:%S %z"
        )
    if html_body is not None:
        msg.set_content(html_body, subtype="html")
    else:
        msg.set_content(body)
    return bytes(msg)


class FakeImapConnection:
    """A fake matching _ImapConnection's interface: no network, no real mailbox."""

    def __init__(self, responses: dict[int, dict[bytes, bytes]]) -> None:
        self._responses = responses
        self.login_calls: list[tuple[str, str]] = []
        self.select_calls: list[tuple[str, bool]] = []
        self.search_calls: list[list[object]] = []

    def login(self, username: str, password: str) -> bytes:
        self.login_calls.append((username, password))
        return b"OK"

    def select_folder(self, folder: str, *, readonly: bool) -> dict[bytes, object]:
        self.select_calls.append((folder, readonly))
        return {}

    def search(self, criteria: list[object]) -> list[int]:
        self.search_calls.append(criteria)
        return list(self._responses)

    def fetch(self, messages: list[int], data: list[str]) -> dict[int, dict[bytes, bytes]]:
        return {msg_id: self._responses[msg_id] for msg_id in messages}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> bool | None:
        del exc_info
        return None


def _config() -> ImapConfig:
    return ImapConfig(host="imap.example.com", username="user", password="pw")


def test_login_and_select_folder_readonly() -> None:
    fake = FakeImapConnection({1: {b"RFC822": _raw_message()}})
    source = ImapEmailSource(_config(), connect=lambda _host: fake)

    source.fetch_since(datetime(2026, 1, 1, tzinfo=UTC))

    assert fake.login_calls == [("user", "pw")]
    assert fake.select_calls == [("INBOX", True)]


def test_fetch_since_returns_plain_text_message() -> None:
    fake = FakeImapConnection(
        {1: {b"RFC822": _raw_message(subject="This week in AI", body="Hello there.")}}
    )
    source = ImapEmailSource(_config(), connect=lambda _host: fake)

    messages = source.fetch_since(datetime(2026, 1, 1, tzinfo=UTC))

    assert len(messages) == 1
    assert messages[0].subject == "This week in AI"
    assert messages[0].body_text == "Hello there."
    assert messages[0].sender == "newsletter@example.com"
    assert messages[0].source_label == "newsletter@example.com"


def test_fetch_since_falls_back_to_html_when_no_plain_text() -> None:
    html = "<html><body><script>evil()</script><p>Real content.</p></body></html>"
    fake = FakeImapConnection({1: {b"RFC822": _raw_message(html_body=html)}})
    source = ImapEmailSource(_config(), connect=lambda _host: fake)

    messages = source.fetch_since(datetime(2026, 1, 1, tzinfo=UTC))

    assert "Real content." in messages[0].body_text
    assert "evil()" not in messages[0].body_text


def test_fetch_since_excludes_messages_received_before_since() -> None:
    fake = FakeImapConnection(
        {
            1: {b"RFC822": _raw_message(date=datetime(2025, 12, 30, tzinfo=UTC))},
            2: {b"RFC822": _raw_message(date=datetime(2026, 1, 5, tzinfo=UTC))},
        }
    )
    source = ImapEmailSource(_config(), connect=lambda _host: fake)

    messages = source.fetch_since(datetime(2026, 1, 1, tzinfo=UTC))

    assert len(messages) == 1
    assert messages[0].received_at == datetime(2026, 1, 5, tzinfo=UTC)


def test_fetch_since_skips_messages_with_no_date_header() -> None:
    fake = FakeImapConnection({1: {b"RFC822": _raw_message(include_date=False)}})
    source = ImapEmailSource(_config(), connect=lambda _host: fake)

    messages = source.fetch_since(datetime(2026, 1, 1, tzinfo=UTC))

    assert messages == []


def test_fetch_since_with_no_search_results_returns_empty_list() -> None:
    fake = FakeImapConnection({})
    source = ImapEmailSource(_config(), connect=lambda _host: fake)

    messages = source.fetch_since(datetime(2026, 1, 1, tzinfo=UTC))

    assert messages == []
