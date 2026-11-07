from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llmhost.contracts import CompletionRequest
from llmhost.provider_claude import ClaudeProvider


@dataclass
class _FakeToolUseBlock:
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class _FakeUsage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class _FakeMessage:
    content: list[_FakeToolUseBlock]
    usage: _FakeUsage


class FakeMessagesClient:
    def __init__(self, tool_input: dict[str, Any], usage: _FakeUsage) -> None:
        self._tool_input = tool_input
        self._usage = usage
        self.create_calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeMessage:  # noqa: ANN401
        self.create_calls.append(kwargs)
        return _FakeMessage(content=[_FakeToolUseBlock(input=self._tool_input)], usage=self._usage)


class FakeAnthropicClient:
    def __init__(self, tool_input: dict[str, Any], usage: _FakeUsage) -> None:
        self.messages = FakeMessagesClient(tool_input, usage)


def test_complete_with_tool_returns_the_tool_input_and_usage() -> None:
    client = FakeAnthropicClient(
        tool_input={"themes": ["a"]},
        usage=_FakeUsage(input_tokens=100, output_tokens=20),
    )
    provider = ClaudeProvider(client=client)

    result = provider.complete_with_tool(
        CompletionRequest(
            model="claude-sonnet-5-5",
            system="system prompt",
            user_message="user message",
            tool_schema={"name": "record", "input_schema": {}},
            tool_name="record",
            max_tokens=1024,
        )
    )

    assert result.tool_input == {"themes": ["a"]}
    assert result.usage.model == "claude-sonnet-5-5"
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 20
    assert client.messages.create_calls[0]["tool_choice"] == {"type": "tool", "name": "record"}
