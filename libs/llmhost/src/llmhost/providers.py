"""Provider registry and spec resolution -- the one place a model is chosen.

A *spec* is ``provider`` or ``provider:model``; the model part may itself contain colons
(``ollama:gpt-oss:120b``). Add a provider by writing ``provider_<name>.py`` and adding ONE
entry to `REGISTRY`; the contract suite (tests/test_provider_contract.py) then fails until
the provider has a harness and passes it. Nothing calling `resolve_model()` changes.
"""

from __future__ import annotations

__arbor__ = {"ring": "llm"}

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from llmhost.errors import LlmConfigError, UnknownProviderError
from llmhost.provider_claude import ClaudeProvider
from llmhost.provider_ollama import DEFAULT_BASE_URL, OllamaProvider, OllamaSettings

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from llmhost.contracts import CompletionRequest, CompletionResult

OLLAMA_URL_ENV = "LLMHOST_OLLAMA_URL"


class Provider(Protocol):
    """The single interface for every LLM call. Contract (enforced by the contract suite):
    returns a `CompletionResult` whose `tool_input` is a JSON object satisfying the request's
    tool schema, or raises a subclass of `llmhost.errors.LlmError` -- never a vendor exception."""

    def complete_with_tool(self, request: CompletionRequest) -> CompletionResult: ...


def _ollama() -> Provider:
    return OllamaProvider(
        OllamaSettings(base_url=os.environ.get(OLLAMA_URL_ENV) or DEFAULT_BASE_URL)
    )


REGISTRY: Mapping[str, Callable[[], Provider]] = {
    "claude": ClaudeProvider,
    "ollama": _ollama,
}


@dataclass(frozen=True, slots=True)
class ModelSpec:
    provider: str
    model: str  # "" when the spec named only a provider


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    provider: Provider
    name: str  # provider name, e.g. "ollama" (for usage ledgers)
    model: str  # "" when the spec named only a provider: the caller supplies its default


def parse_spec(spec: str) -> ModelSpec:
    name, _, model = spec.strip().partition(":")
    if not name:
        msg = f"Invalid llmhost spec {spec!r}: expected 'provider' or 'provider:model'"
        raise LlmConfigError(msg)
    return ModelSpec(provider=name.lower(), model=model.strip())


def resolve_model(spec: str) -> ResolvedModel:
    parsed = parse_spec(spec)
    factory = REGISTRY.get(parsed.provider)
    if factory is None:
        msg = (
            f"Unknown llmhost provider: {parsed.provider!r} (known: {', '.join(sorted(REGISTRY))})"
        )
        raise UnknownProviderError(msg)
    return ResolvedModel(provider=factory(), name=parsed.provider, model=parsed.model)


def resolve(spec: str) -> Provider:
    """The provider part of `spec`. Use `resolve_model` when the model part matters."""
    return resolve_model(spec).provider
