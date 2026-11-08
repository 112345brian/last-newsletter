from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from last_newsletter_adapter_summarizer.anthropic_summarizer import AnthropicSummarizer
from llmhost import CompletionResult, Usage
from ranked_digest.entities import EmailMessage, Theme

if TYPE_CHECKING:
    from pathlib import Path

    from llmhost import CompletionRequest


class FakeProvider:
    """A fake matching llmhost.Provider's interface: no network, no real API call."""

    def __init__(self, themes: list[dict[str, Any]]) -> None:
        self._themes = themes
        self.complete_calls: list[CompletionRequest] = []

    def complete_with_tool(self, request: CompletionRequest) -> CompletionResult:
        self.complete_calls.append(request)
        return CompletionResult(
            tool_input={"themes": self._themes},
            usage=Usage(model="fake-model", input_tokens=10, output_tokens=5),
        )


def _summarizer(
    themes: list[dict[str, Any]], *, usage_ledger_path: Path | None = None
) -> tuple[AnthropicSummarizer, FakeProvider]:
    provider = FakeProvider(themes)
    summarizer = AnthropicSummarizer(
        _provider_override=provider, usage_ledger_path=usage_ledger_path
    )
    return summarizer, provider


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
    summarizer, provider = _summarizer(themes=[])

    result = summarizer.summarize([], prior_themes=[], today=date(2026, 1, 5))

    assert result == []
    assert provider.complete_calls == []


def test_summarize_parses_a_new_theme_from_the_tool_response() -> None:
    summarizer, provider = _summarizer(
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
    message = _message()

    [theme] = summarizer.summarize([message], prior_themes=[], today=date(2026, 1, 5))

    assert theme.title == "Rust 2.0 released"
    assert theme.source_message_ids == ("<1@example.com>",)
    assert theme.theme_key == "rust-2-0"
    assert theme.streak == 1
    assert theme.carried_forward is False
    assert theme.first_seen == date(2026, 1, 5)
    assert provider.complete_calls[0].model == "claude-sonnet-5-5"


def test_summarize_bumps_streak_for_a_carried_forward_theme() -> None:
    prior = Theme(
        title="Rust 2.0 released",
        summary="Still ongoing.",
        source_count=2,
        theme_key="rust-2-0",
        first_seen=date(2025, 12, 29),
        streak=2,
    )
    summarizer, _provider = _summarizer(
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

    [theme] = summarizer.summarize([], prior_themes=[prior], today=date(2026, 1, 5))

    assert theme.carried_forward is True
    assert theme.streak == 3
    assert theme.first_seen == date(2025, 12, 29)


def test_summarize_parses_relevant_until() -> None:
    summarizer, _provider = _summarizer(
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

    [theme] = summarizer.summarize([_message()], prior_themes=[], today=date(2026, 1, 5))

    assert theme.relevant_until == date(2026, 5, 1)


def test_summarize_ignores_an_unparseable_relevant_until() -> None:
    summarizer, _provider = _summarizer(
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

    [theme] = summarizer.summarize([_message()], prior_themes=[], today=date(2026, 1, 5))

    assert theme.relevant_until is None


def test_summarize_records_usage_when_a_ledger_path_is_given(tmp_path: Path) -> None:
    ledger_path = tmp_path / "usage.jsonl"
    summarizer, _provider = _summarizer(
        themes=[
            {
                "title": "Something",
                "summary": "Summary.",
                "source_message_ids": ["<1@example.com>"],
                "theme_key": None,
                "relevant_until": None,
                "carried_forward": False,
            }
        ],
        usage_ledger_path=ledger_path,
    )

    summarizer.summarize([_message()], prior_themes=[], today=date(2026, 1, 5))

    assert ledger_path.exists()
    assert "fake-model" in ledger_path.read_text()
