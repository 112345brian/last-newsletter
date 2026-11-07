"""Ollama provider: the tool's JSON Schema becomes Ollama's `format`, so the model is
constrained to produce the tool input directly. Native `/api/chat`, stdlib only, no streaming."""

from __future__ import annotations

__arbor__ = {"ring": "llm"}

import http.client
import json
import time
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from llmhost.checks import clean_input, input_schema, validate_output, with_retries
from llmhost.contracts import CompletionResult, Usage
from llmhost.errors import (
    LlmConfigError,
    LlmOutputError,
    LlmProtocolError,
    LlmTimeoutError,
    LlmUnavailableError,
)
from llmhost.transport import Transport, UrllibTransport

if TYPE_CHECKING:
    from collections.abc import Callable

    from llmhost.contracts import CompletionRequest

DEFAULT_BASE_URL = "http://localhost:11434"
_HTTP_OK = 200
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class OllamaSettings:
    """Connection and sampling knobs. `think=False` turns thinking off (qwen3 family);
    "low"/"medium"/"high" sets gpt-oss effort; None leaves the server default."""

    base_url: str = DEFAULT_BASE_URL
    timeout_s: float = 300.0
    max_retries: int = 2  # retries after the first attempt
    backoff_s: float = 1.0
    num_ctx: int = 16384
    think: bool | str | None = None
    seed: int | None = 0  # fixed sampling seed so the same prompt gives the same answer


class OllamaProvider:
    def __init__(
        self,
        settings: OllamaSettings | None = None,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        cfg = settings or OllamaSettings()
        parts = urllib.parse.urlsplit(cfg.base_url)
        if parts.scheme not in {"http", "https"} or parts.hostname is None:
            msg = "ollama base_url must be an http(s) URL"
            raise LlmConfigError(msg)
        self._cfg = cfg
        self._url = cfg.base_url.rstrip("/") + "/api/chat"
        self._transport: Transport = transport or UrllibTransport()
        self._sleep = sleep

    def complete_with_tool(self, request: CompletionRequest) -> CompletionResult:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": clean_input(request.system)},
                {"role": "user", "content": clean_input(request.user_message)},
            ],
            "stream": False,
            "format": input_schema(request) or "json",
            "options": {
                "temperature": 0,
                "seed": self._cfg.seed,
                "num_ctx": self._cfg.num_ctx,
                "num_predict": request.max_tokens,
            },
        }
        if self._cfg.seed is None:
            del payload["options"]["seed"]
        if self._cfg.think is not None:
            payload["think"] = self._cfg.think
        body = json.dumps(payload).encode("utf-8")
        raw = with_retries(
            lambda: self._post(body),
            max_retries=self._cfg.max_retries,
            backoff_s=self._cfg.backoff_s,
            sleep=self._sleep,
        )
        return _result(raw, request)

    def _post(self, body: bytes) -> bytes:
        try:
            status, raw = self._transport.post(self._url, body, timeout_s=self._cfg.timeout_s)
        except TimeoutError as exc:
            msg = f"no answer within {self._cfg.timeout_s:g}s"
            raise LlmTimeoutError(msg) from exc
        except (OSError, http.client.HTTPException) as exc:
            msg = f"cannot reach the ollama server: {type(exc).__name__}"
            raise LlmUnavailableError(msg) from exc
        if status in _RETRYABLE_STATUS:
            msg = f"ollama answered HTTP {status}"
            raise LlmUnavailableError(msg)
        if status != _HTTP_OK:
            msg = f"unexpected HTTP {status}"
            raise LlmProtocolError(msg)
        return raw


def _result(raw: bytes, request: CompletionRequest) -> CompletionResult:
    try:
        envelope = json.loads(raw)
        content = envelope["message"]["content"]
    except (ValueError, KeyError, TypeError) as exc:
        msg = "response is not an Ollama chat envelope"
        raise LlmProtocolError(msg) from exc
    if not isinstance(content, str) or not content.strip():
        msg = "model returned empty output"
        raise LlmOutputError(msg)
    try:
        parsed = json.loads(content)
    except ValueError as exc:
        msg = "model output is not JSON"
        raise LlmOutputError(msg) from exc
    return CompletionResult(
        tool_input=validate_output(parsed, request), usage=_usage(envelope, request.model)
    )


def _usage(envelope: dict[str, Any], model: str) -> Usage:
    prompt, evaluated = envelope.get("prompt_eval_count"), envelope.get("eval_count")
    if isinstance(prompt, int) and isinstance(evaluated, int):
        return Usage(model=model, input_tokens=prompt, output_tokens=evaluated)
    return Usage(model=model, tokens_available=False)
