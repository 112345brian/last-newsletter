"""Ollama native `/api/chat` client: stdlib `urllib` only, no streaming, no tools.

The transport is injectable so tests run without a socket; `sleep` is injectable so retries
do not slow the suite. Nothing is read from the environment here (the CLI does that).
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import http.client
import json
import time
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from last_newsletter_adapter_events.errors import (
    ModelOutputError,
    ModelProtocolError,
    ModelTimeoutError,
    ModelUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_HTTP_OK = 200
_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class OllamaConfig:
    """Everything the client needs; built by the caller (the CLI reads env vars)."""

    model: str
    base_url: str = "http://localhost:11434"
    timeout_s: float = 300.0
    max_retries: int = 2  # retries after the first attempt
    backoff_s: float = 1.0
    temperature: float = 0.0
    num_ctx: int = 16384
    num_predict: int = 4096
    # `False` turns thinking off (qwen3 family); "low"/"medium"/"high" sets gpt-oss effort;
    # None leaves the server default.
    think: bool | str | None = None


class Transport(Protocol):
    def post(self, url: str, body: bytes, *, timeout_s: float) -> tuple[int, bytes]:
        """POST JSON, return (status, body). Raise TimeoutError / OSError on network trouble."""
        ...


class UrllibTransport:
    """Plain `http.client` (stdlib): no redirects, no proxies, no scheme surprises."""

    def post(self, url: str, body: bytes, *, timeout_s: float) -> tuple[int, bytes]:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in {"http", "https"} or parts.hostname is None:
            msg = "base_url must be an http(s) URL"
            raise ValueError(msg)
        conn_type = (
            http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        )
        conn = conn_type(parts.hostname, parts.port, timeout=timeout_s)
        try:
            conn.request(
                "POST",
                parts.path or "/",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            return resp.status, resp.read()
        except TimeoutError as exc:
            raise TimeoutError from exc
        finally:
            conn.close()


class OllamaClient:
    """One call: system + user text in, the model's JSON-schema-constrained text out."""

    def __init__(
        self,
        config: OllamaConfig,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._transport: Transport = transport or UrllibTransport()
        self._sleep = sleep

    @property
    def model(self) -> str:
        return self._config.model

    def chat(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        """Return the assistant message content. Raises a `ModelBackendError` subclass."""
        cfg = self._config
        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": schema,
            "options": {
                "temperature": cfg.temperature,
                "num_ctx": cfg.num_ctx,
                "num_predict": cfg.num_predict,
            },
        }
        if cfg.think is not None:
            payload["think"] = cfg.think
        body = json.dumps(payload).encode("utf-8")
        url = cfg.base_url.rstrip("/") + "/api/chat"

        last: Exception | None = None
        for attempt in range(cfg.max_retries + 1):
            if attempt:
                self._sleep(cfg.backoff_s * 2 ** (attempt - 1))
            try:
                status, raw = self._transport.post(url, body, timeout_s=cfg.timeout_s)
            except TimeoutError as exc:
                last = ModelTimeoutError(f"no answer within {cfg.timeout_s:g}s")
                last.__cause__ = exc
                continue
            except OSError as exc:  # ConnectionError, refused, DNS, reset
                last = ModelUnavailableError(f"cannot reach {cfg.base_url}: {type(exc).__name__}")
                last.__cause__ = exc
                continue
            if status in _RETRYABLE_STATUS:
                last = ModelUnavailableError(f"server answered HTTP {status}")
                continue
            if status != _HTTP_OK:
                msg = f"unexpected HTTP {status}"
                raise ModelProtocolError(msg)
            return _content(raw)
        raise last or ModelUnavailableError("no attempt was made")


def _content(raw: bytes) -> str:
    try:
        envelope = json.loads(raw)
        content = envelope["message"]["content"]
    except (ValueError, KeyError, TypeError) as exc:
        msg = "response is not an Ollama chat envelope"
        raise ModelProtocolError(msg) from exc
    if not isinstance(content, str) or not content.strip():
        msg = "model returned empty output"
        raise ModelOutputError(msg)
    return content
