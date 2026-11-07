"""Provider registry: resolves a provider name to its adapter.

Add a second provider by writing `provider_<name>.py` (same shape as
`provider_claude.py` — one class with a `complete_with_tool` method matching
`Provider` below) and registering its name in `resolve`. Nothing calling
`resolve()` needs to change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from llmhost.provider_claude import ClaudeProvider

if TYPE_CHECKING:
    from llmhost.contracts import CompletionRequest, CompletionResult


class Provider(Protocol):
    def complete_with_tool(self, request: CompletionRequest) -> CompletionResult: ...


def resolve(name: str) -> Provider:
    if name == "claude":
        return ClaudeProvider()
    msg = f"Unknown llmhost provider: {name!r}"
    raise ValueError(msg)
