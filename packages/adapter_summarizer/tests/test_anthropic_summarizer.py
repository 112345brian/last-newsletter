from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from last_newsletter_adapter_summarizer.anthropic_summarizer import AnthropicSummarizer
from last_newsletter_core.entities import EmailMessage, Theme


@dataclass
class _FakeToolUseBlock:
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class _FakeMessage:
    content: list[_FakeToolUseBlock]


class FakeMessagesClient:
    """A fake matching _MessagesClient's interface: no network, no real API call."""

    def __init__(self, themes: list[dict[str, Any]]) -> None:
        self._themes = themes
        self.create_calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeMessage:  # noqa: ANN401
        self.create_calls.append(kwargs)
        return _FakeMessage(content=[_FakeToolUseBlock(input={"themes": self._themes})])


class FakeAnthropicClient:
    def __init__(self, themes: list[dict[str, Any]]) -> None:
        self.messages = FakeMessagesClient(themes)


def _message(message_id: str = "<1@example.com>") -> EmailMessage:
    return EmailMessage(
        message_id=message_id,
        sender="newsletter@example.com",
        subject="This week",
        received_at=datetime(2026, 1, 5, tzinfo=UTC),
        body_text="Some body text.",
        source_label="newsletter@example.com",
    )


def test_summarize_with_no_messages_and_no_prior_themes_skips_the_api_call() -> None:
    client = FakeAnthropicClient(themes=[])
    summarizer = AnthropicSummarizer(client=client)

    result = summarizer.summarize([], prior_themes=[], today=date(2026, 1, 5))

    assert result == []
    assert client.messages.create_calls == []


def test_summarize_parses_a_new_theme_from_the_tool_response() -> None:
    client = FakeAnthropicClient(
        themes=[
            {
                "title": "Rust 2.0 released",
                "summary": "Several newsletters covered the release.",
                "source_message_ids": ["<1@example.com>"],
                "theme_key": "rust-2-0",
                "relevant_until": None,
                "carried_forward": False,
            }
        ]
    )
    summarizer = AnthropicSummarizer(client=client)
    message = _message()

    [theme] = summarizer.summarize([message], prior_themes=[], today=date(2026, 1, 5))

    assert theme.title == "Rust 2.0 released"
    assert theme.source_message_ids == ("<1@example.com>",)
    assert theme.theme_key == "rust-2-0"
    assert theme.streak == 1
    assert theme.carried_forward is False
    assert theme.first_seen == date(2026, 1, 5)
    assert client.messages.create_calls[0]["model"] == summarizer._model  # noqa: SLF001


def test_summarize_bumps_streak_for_a_carried_forward_theme() -> None:
    prior = Theme(
        title="Rust 2.0 released",
        summary="Still ongoing.",
        source_count=2,
        theme_key="rust-2-0",
        first_seen=date(2025, 12, 29),
        streak=2,
    )
    client = FakeAnthropicClient(
        themes=[
            {
                "title": "Rust 2.0 adoption",
                "summary": "Still being discussed.",
                "source_message_ids": [],
                "theme_key": "rust-2-0",
                "relevant_until": None,
                "carried_forward": True,
            }
        ]
    )
    summarizer = AnthropicSummarizer(client=client)

    [theme] = summarizer.summarize([], prior_themes=[prior], today=date(2026, 1, 5))

    assert theme.carried_forward is True
    assert theme.streak == 3
    assert theme.first_seen == date(2025, 12, 29)


def test_summarize_parses_relevant_until() -> None:
    client = FakeAnthropicClient(
        themes=[
            {
                "title": "PyCon 2026",
                "summary": "Conference coming up.",
                "source_message_ids": ["<1@example.com>"],
                "theme_key": "pycon-2026",
                "relevant_until": "2026-05-01",
                "carried_forward": False,
            }
        ]
    )
    summarizer = AnthropicSummarizer(client=client)

    [theme] = summarizer.summarize([_message()], prior_themes=[], today=date(2026, 1, 5))

    assert theme.relevant_until == date(2026, 5, 1)


def test_summarize_ignores_an_unparseable_relevant_until() -> None:
    client = FakeAnthropicClient(
        themes=[
            {
                "title": "Something",
                "summary": "Summary.",
                "source_message_ids": [],
                "theme_key": None,
                "relevant_until": "not-a-date",
                "carried_forward": False,
            }
        ]
    )
    summarizer = AnthropicSummarizer(client=client)

    [theme] = summarizer.summarize([_message()], prior_themes=[], today=date(2026, 1, 5))

    assert theme.relevant_until is None
