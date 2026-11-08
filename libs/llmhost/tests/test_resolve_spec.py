"""`provider[:model]` specs and the registry."""

from __future__ import annotations

import pytest

from llmhost import (
    REGISTRY,
    LlmConfigError,
    OllamaProvider,
    UnknownProviderError,
    parse_spec,
    resolve,
    resolve_model,
)
from llmhost.provider_claude import ClaudeProvider


@pytest.mark.parametrize(
    ("spec", "provider", "model"),
    [
        ("claude", "claude", ""),
        ("claude:claude-sonnet-5-5", "claude", "claude-sonnet-5-5"),
        ("ollama:gpt-oss:120b", "ollama", "gpt-oss:120b"),
        ("  Ollama:qwen3:8b ", "ollama", "qwen3:8b"),
        ("ollama:", "ollama", ""),
    ],
)
def test_parse_spec(spec: str, provider: str, model: str) -> None:
    parsed = parse_spec(spec)
    assert (parsed.provider, parsed.model) == (provider, model)


@pytest.mark.parametrize("spec", ["", "   ", ":model"])
def test_blank_spec_is_a_config_error(spec: str) -> None:
    with pytest.raises(LlmConfigError):
        parse_spec(spec)


def test_unknown_provider_lists_the_known_ones() -> None:
    with pytest.raises(UnknownProviderError, match="known: claude, ollama"):
        resolve("gemini:flash")


def test_unknown_provider_is_still_a_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown llmhost provider"):
        resolve("nope")


def test_resolve_model_returns_provider_name_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    local = resolve_model("ollama:gpt-oss:120b")
    assert isinstance(local.provider, OllamaProvider)
    assert (local.name, local.model) == ("ollama", "gpt-oss:120b")
    cloud = resolve_model("claude:some-model")
    assert isinstance(cloud.provider, ClaudeProvider)
    assert (cloud.name, cloud.model) == ("claude", "some-model")


def test_every_registry_entry_builds_a_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    for name in REGISTRY:
        assert callable(resolve(name).complete_with_tool)


def test_ollama_url_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLMHOST_OLLAMA_URL", "ftp://nope")
    with pytest.raises(LlmConfigError):
        resolve("ollama")
