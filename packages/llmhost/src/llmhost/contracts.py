"""Typed request/result contracts shared by every provider adapter."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    """Everything one `Provider.complete_with_tool` call needs, bundled instead of passed
    as six separate keyword arguments."""

    model: str
    system: str
    user_message: str
    tool_schema: dict[str, object] = field(default_factory=dict)
    tool_name: str = ""
    max_tokens: int = 4096


@dataclass(frozen=True, slots=True)
class Usage:
    """Per-call token accounting. ``tokens_available=False`` means the call succeeded
    but the response had no usage block to report -- the token fields are all 0, but
    that's "unknown", not "zero tokens used"."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    tokens_available: bool = True


@dataclass(frozen=True, slots=True)
class CompletionResult:
    """A completed `complete_with_tool` call: the tool's parsed input, and what it cost."""

    tool_input: dict[str, object]
    usage: Usage
