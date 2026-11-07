"""Claude provider adapter: forces a single tool call via the `anthropic` SDK so a caller
gets back structured JSON instead of prose it would have to parse, and reports the real
token usage from the response rather than leaving a caller to estimate it."""

from __future__ import annotations

__arbor__ = {"ring": "llm"}

import time
from typing import TYPE_CHECKING, Protocol, TypedDict, Unpack, cast

import anthropic

from llmhost.checks import clean_input, validate_output, with_retries
from llmhost.contracts import CompletionResult, Usage
from llmhost.errors import (
    LlmOutputError,
    LlmProtocolError,
    LlmTimeoutError,
    LlmUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

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


_RETRYABLE_STATUS = frozenset({408, 409, 429})
_SERVER_ERROR = 500


class ClaudeProvider:
    def __init__(
        self,
        *,
        client: _AnthropicClient | None = None,
        max_retries: int = 2,
        backoff_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """`client` defaults to a real `anthropic.Anthropic()` (reads `ANTHROPIC_API_KEY`
        from the environment); tests pass a fake instead. Retries are llmhost's own (the
        SDK's are switched off) so every provider retries the same way."""
        self._client: _AnthropicClient = (
            client
            if client is not None
            else cast("_AnthropicClient", anthropic.Anthropic(max_retries=0))
        )
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._sleep = sleep

    def complete_with_tool(self, request: CompletionRequest) -> CompletionResult:
        response = with_retries(
            lambda: self._create(request),
            max_retries=self._max_retries,
            backoff_s=self._backoff_s,
            sleep=self._sleep,
        )
        tool_use = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use is None:
            msg = "model returned no tool call"
            raise LlmOutputError(msg)
        tool_input = validate_output(tool_use.input, request)
        usage = getattr(response, "usage", None)
        if usage is None:
            return CompletionResult(
                tool_input=tool_input, usage=Usage(model=request.model, tokens_available=False)
            )
        return CompletionResult(
            tool_input=tool_input,
            usage=Usage(
                model=request.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
                cache_read_input_tokens=usage.cache_read_input_tokens or 0,
            ),
        )

    def _create(self, request: CompletionRequest) -> Message:
        """One SDK call; vendor exceptions leave here as typed llmhost errors only."""
        try:
            return self._client.messages.create(
                model=request.model,
                max_tokens=request.max_tokens,
                system=clean_input(request.system),
                tools=[cast("ToolParam", request.tool_schema)],
                tool_choice={"type": "tool", "name": request.tool_name},
                messages=[{"role": "user", "content": clean_input(request.user_message)}],
            )
        except (anthropic.APITimeoutError, TimeoutError) as exc:
            msg = "no answer from the Claude API in time"
            raise LlmTimeoutError(msg) from exc
        except (anthropic.APIConnectionError, ConnectionError) as exc:
            msg = f"cannot reach the Claude API: {type(exc).__name__}"
            raise LlmUnavailableError(msg) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code in _RETRYABLE_STATUS or exc.status_code >= _SERVER_ERROR:
                msg = f"Claude API answered HTTP {exc.status_code}"
                raise LlmUnavailableError(msg) from exc
            msg = f"Claude API answered HTTP {exc.status_code}"
            raise LlmProtocolError(msg) from exc
        except anthropic.AnthropicError as exc:
            msg = f"Claude SDK error: {type(exc).__name__}"
            raise LlmProtocolError(msg) from exc
