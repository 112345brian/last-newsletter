"""Pins what every existing caller of `llmhost` relies on, written BEFORE the provider work.

Callers at the time of writing (grep of `resolve(` / `complete_with_tool` / `llmhost`):
  - `adapter_summarizer.AnthropicSummarizer`: `resolve(name)`, then reads `.tool_input` and
    `.usage` from the result and passes `.usage` to `record_usage`.
  - fakes of `Provider` in `adapter_summarizer/tests` (duck-typed `complete_with_tool`).
These tests must keep passing unchanged.
"""

from __future__ import annotations

import pytest
from llmhost import CompletionRequest, CompletionResult, Usage, resolve
from llmhost.provider_claude import ClaudeProvider


def test_resolve_claude_returns_a_claude_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert isinstance(resolve("claude"), ClaudeProvider)


def test_resolve_unknown_name_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown llmhost provider"):
        resolve("nope")


def test_request_defaults_are_unchanged() -> None:
    request = CompletionRequest(model="m", system="s", user_message="u")
    assert request.tool_schema == {}
    assert request.tool_name == ""
    assert request.max_tokens == 4096


def test_usage_defaults_mean_available_and_zero() -> None:
    usage = Usage(model="m")
    assert (usage.input_tokens, usage.output_tokens, usage.tokens_available) == (0, 0, True)


def test_result_exposes_tool_input_and_usage() -> None:
    result = CompletionResult(tool_input={"a": 1}, usage=Usage(model="m"))
    assert result.tool_input == {"a": 1}
    assert result.usage.model == "m"
