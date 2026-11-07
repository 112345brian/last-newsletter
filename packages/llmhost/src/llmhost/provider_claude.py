"""Claude provider adapter: forces a single tool call via the `anthropic` SDK so a caller
gets back structured JSON instead of prose it would have to parse, and reports the real
token usage from the response rather than leaving a caller to estimate it."""

from __future__ import annotations

__arbor__ = {"ring": "libs"}

from typing import TYPE_CHECKING, Protocol, TypedDict, Unpack, cast

import anthropic

from llmhost.contracts import CompletionResult, Usage

if TYPE_CHECKING:
    from anthropic.types import Message, MessageParam, ToolChoiceToolParam, ToolParam

    from llmhost.contracts import CompletionRequest


class _CreateMessageParams(TypedDict):
    """Exactly the keyword arguments `complete_with_tool` passes to `messages.create` --
    named here so the call is fully typed without `_MessagesClient.create` itself needing
    more than one parameter."""

    model: str
    max_tokens: int
    system: str
    tools: list[ToolParam]
    tool_choice: ToolChoiceToolParam
    messages: list[MessageParam]


class _MessagesClient(Protocol):
    def create(self, **kwargs: Unpack[_CreateMessageParams]) -> Message: ...


class _AnthropicClient(Protocol):
    """The subset of anthropic.Anthropic's interface this adapter needs -- small enough
    to fake in tests instead of calling the real API."""

    @property
    def messages(self) -> _MessagesClient: ...


class ClaudeProvider:
    def __init__(self, *, client: _AnthropicClient | None = None) -> None:
        """`client` defaults to a real `anthropic.Anthropic()` (reads `ANTHROPIC_API_KEY`
        from the environment); tests pass a fake instead."""
        self._client: _AnthropicClient = (
            client if client is not None else cast("_AnthropicClient", anthropic.Anthropic())
        )

    def complete_with_tool(self, request: CompletionRequest) -> CompletionResult:
        response = self._client.messages.create(
            model=request.model,
            max_tokens=request.max_tokens,
            system=request.system,
            tools=[cast("ToolParam", request.tool_schema)],
            tool_choice={"type": "tool", "name": request.tool_name},
            messages=[{"role": "user", "content": request.user_message}],
        )
        tool_use = next(block for block in response.content if block.type == "tool_use")
        usage = response.usage
        return CompletionResult(
            tool_input=dict(tool_use.input),
            usage=Usage(
                model=request.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
                cache_read_input_tokens=usage.cache_read_input_tokens or 0,
            ),
        )
