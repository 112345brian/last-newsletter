from datetime import UTC, datetime

from last_newsletter_core.entities import Cadence, Digest, EmailMessage, Theme
from last_newsletter_core.use_cases.build_digest import BuildDigestRequest, BuildDigestUseCase


class FakeEmailSource:
    def __init__(self, messages: list[EmailMessage]) -> None:
        self._messages = messages

    def fetch_since(self, since: datetime) -> list[EmailMessage]:
        return self._messages


class FakeSummarizer:
    def __init__(self, themes: list[Theme]) -> None:
        self._themes = themes

    def summarize(self, messages: list[EmailMessage]) -> list[Theme]:
        return self._themes


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: Digest | None = None

    def publish(self, digest: Digest) -> None:
        self.published = digest


def _message(source: str) -> EmailMessage:
    return EmailMessage(
        message_id=f"id-{source}",
        sender=f"{source}@example.com",
        subject="subject",
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
        body_text="body",
        source_label=source,
    )


def test_execute_ranks_themes_by_source_count_and_publishes() -> None:
    messages = [_message("a"), _message("b"), _message("c")]
    themes = [
        Theme(title="low", summary="s", source_count=1),
        Theme(title="high", summary="s", source_count=3),
    ]
    publisher = RecordingPublisher()
    use_case = BuildDigestUseCase(
        email_source=FakeEmailSource(messages),
        summarizer=FakeSummarizer(themes),
        publisher=publisher,
    )
    request = BuildDigestRequest(
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=datetime(2026, 1, 8, tzinfo=UTC),
        cadence=Cadence.WEEKLY,
    )

    digest = use_case.execute(request)

    assert [t.title for t in digest.themes] == ["high", "low"]
    assert digest.total_messages == 3
    assert digest.total_sources == 3
    assert publisher.published is digest


def test_execute_with_no_messages_still_publishes_empty_digest() -> None:
    publisher = RecordingPublisher()
    use_case = BuildDigestUseCase(
        email_source=FakeEmailSource([]),
        summarizer=FakeSummarizer([]),
        publisher=publisher,
    )
    request = BuildDigestRequest(
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=datetime(2026, 1, 2, tzinfo=UTC),
        cadence=Cadence.DAILY,
    )

    digest = use_case.execute(request)

    assert digest.themes == ()
    assert digest.total_messages == 0
    assert publisher.published is digest
