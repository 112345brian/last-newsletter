from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypedDict, Unpack, cast

from llmhost.contracts import CompletionRequest
from llmhost.provider_claude import ClaudeProvider

if TYPE_CHECKING:
    from anthropic.types import Message, MessageParam, ToolChoiceToolParam, ToolParam


class _CreateParams(TypedDict):
    """Mirrors `provider_claude._CreateMessageParams` -- what `_MessagesClient.create`
    actually needs, so this fake's signature structurally matches the real protocol."""

    model: str
    max_tokens: int
    system: str
    tools: list[ToolParam]
    tool_choice: ToolChoiceToolParam
    messages: list[MessageParam]


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
    """Matches `_MessagesClient`'s own signature -- a fake, not a `**kwargs` catch-all."""

    def __init__(self, tool_input: dict[str, Any], usage: _FakeUsage) -> None:
        self._tool_input = tool_input
        self._usage = usage
        self.tool_choices: list[ToolChoiceToolParam] = []

    def create(self, **kwargs: Unpack[_CreateParams]) -> Message:
        self.tool_choices.append(kwargs["tool_choice"])
        fake = _FakeMessage(content=[_FakeToolUseBlock(input=self._tool_input)], usage=self._usage)
        return cast("Message", fake)


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
    assert client.messages.tool_choices[0] == {"type": "tool", "name": "record"}
