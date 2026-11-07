"""Ollama specifics beyond the shared contract: the request it sends and its envelope."""

from __future__ import annotations

import json

import pytest

from llmhost import (
    CompletionRequest,
    LlmConfigError,
    LlmOutputError,
    LlmProtocolError,
    LlmUnavailableError,
    OllamaProvider,
    OllamaSettings,
)

SCHEMA: dict[str, object] = {
    "name": "t",
    "description": "d",
    "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}},
}


class Scripted:
    def __init__(self, status: int = 200, body: bytes = b"") -> None:
        self.status, self.body = status, body
        self.calls: list[tuple[str, dict[str, object], float]] = []

    def post(self, url: str, body: bytes, *, timeout_s: float) -> tuple[int, bytes]:
        self.calls.append((url, json.loads(body), timeout_s))
        return self.status, self.body


def reply(content: str, **extra: object) -> bytes:
    return json.dumps({"message": {"content": content}, **extra}).encode()


def req(
    *, tool_schema: dict[str, object] | None = None, max_tokens: int = 4096
) -> CompletionRequest:
    return CompletionRequest(
        model="m",
        system="s",
        user_message="u",
        tool_schema=tool_schema or {},
        max_tokens=max_tokens,
    )


def test_schema_becomes_format_and_sampling_is_deterministic() -> None:
    transport = Scripted(body=reply('{"n": 1}'))
    provider = OllamaProvider(
        OllamaSettings(base_url="http://h:1/", think=False), transport=transport
    )
    provider.complete_with_tool(req(tool_schema=SCHEMA, max_tokens=99))
    url, payload, _ = transport.calls[0]
    assert url == "http://h:1/api/chat"
    assert payload["format"] == SCHEMA["input_schema"]
    assert payload["options"] == {"temperature": 0, "num_ctx": 16384, "num_predict": 99}
    assert payload["think"] is False
    assert payload["stream"] is False


def test_no_schema_asks_for_plain_json() -> None:
    transport = Scripted(body=reply("{}"))
    OllamaProvider(transport=transport).complete_with_tool(req())
    assert transport.calls[0][1]["format"] == "json"


def test_a_bare_schema_is_accepted_too() -> None:
    transport = Scripted(body=reply('{"n": 1}'))
    bare: dict[str, object] = {"type": "object", "properties": {"n": {"type": "integer"}}}
    OllamaProvider(transport=transport).complete_with_tool(req(tool_schema=bare))
    assert transport.calls[0][1]["format"] == bare


def test_usage_counts_come_from_ollama() -> None:
    transport = Scripted(body=reply("{}", prompt_eval_count=5, eval_count=2))
    usage = OllamaProvider(transport=transport).complete_with_tool(req()).usage
    assert (usage.input_tokens, usage.output_tokens, usage.tokens_available) == (5, 2, True)


def test_a_body_that_is_not_an_envelope_is_a_protocol_error() -> None:
    with pytest.raises(LlmProtocolError):
        OllamaProvider(transport=Scripted(body=b"<html>")).complete_with_tool(req())


def test_non_string_content_is_an_output_error() -> None:
    body = json.dumps({"message": {"content": None}}).encode()
    with pytest.raises(LlmOutputError):
        OllamaProvider(transport=Scripted(body=body)).complete_with_tool(req())


def test_nothing_listening_is_unavailable_without_real_sleeping() -> None:
    settings = OllamaSettings(base_url="http://127.0.0.1:9", timeout_s=1, max_retries=1)
    slept: list[float] = []
    provider = OllamaProvider(settings, sleep=slept.append)
    with pytest.raises(LlmUnavailableError):
        provider.complete_with_tool(req())
    assert slept == [1.0]


@pytest.mark.parametrize("url", ["", "localhost:11434", "ftp://h", "http://"])
def test_bad_base_url_is_a_config_error(url: str) -> None:
    with pytest.raises(LlmConfigError):
        OllamaProvider(OllamaSettings(base_url=url))
