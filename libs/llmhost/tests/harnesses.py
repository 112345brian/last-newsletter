"""One harness per registered provider: scripts what the vendor does, records what it was sent.

`Step.kind` is one of: ok, timeout, unavailable, server_error, bad_status, empty, malformed,
wrong_shape, schema_violation. The last scripted step repeats. Claude is faked at the SDK
boundary (a fake client raising/returning the SDK's own types); Ollama is faked as a real
HTTP server on 127.0.0.1, so the production transport is exercised too.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Protocol, cast

import anthropic
import httpx2 as httpx

from llmhost.provider_claude import ClaudeProvider
from llmhost.provider_ollama import OllamaProvider, OllamaSettings

if TYPE_CHECKING:
    from llmhost import Provider

MODEL = "test-model"
GOOD: dict[str, object] = {"n": 3, "label": "a"}
BAD_SHAPE: dict[str, object] = {"wrong": 1}


@dataclass(frozen=True)
class Step:
    kind: str = "ok"
    tool_input: dict[str, object] = field(default_factory=lambda: dict(GOOD))
    tokens: tuple[int, int] | None = (11, 7)  # (input, output); None = vendor reports nothing


class Harness(Protocol):
    name: str
    attempts: int
    sent: list[str]  # every system/user text the vendor was handed, one entry per text

    def build(self, *steps: Step) -> Provider: ...
    def close(self) -> None: ...


def _step_at(steps: list[Step], n: int) -> Step:
    return steps[min(n, len(steps) - 1)]


# --------------------------------------------------------------------------- Claude
_REQ = httpx.Request("POST", "https://claude.invalid/v1/messages")


class _FakeMessages:
    def __init__(self, owner: ClaudeHarness) -> None:
        self._owner = owner

    def create(self, **kwargs: object) -> SimpleNamespace:
        owner = self._owner
        step = _step_at(owner.steps, owner.attempts)
        owner.attempts += 1
        owner.sent.append(str(kwargs["system"]))
        messages = cast("list[dict[str, str]]", kwargs["messages"])
        owner.sent.extend(m["content"] for m in messages)
        return owner.respond(step)


class ClaudeHarness:
    name = "claude"

    def __init__(self) -> None:
        self.attempts = 0
        self.sent: list[str] = []
        self.steps: list[Step] = []

    def build(self, *steps: Step) -> Provider:
        self.steps = list(steps)
        client = SimpleNamespace(messages=_FakeMessages(self))
        return ClaudeProvider(client=client, max_retries=2, backoff_s=0, sleep=lambda _s: None)

    def close(self) -> None:
        return None

    def respond(self, step: Step) -> SimpleNamespace:
        kind = step.kind
        if kind == "timeout":
            raise anthropic.APITimeoutError(request=_REQ)
        if kind == "unavailable":
            raise anthropic.APIConnectionError(request=_REQ)
        if kind in {"server_error", "bad_status"}:
            code = 500 if kind == "server_error" else 400
            response = httpx.Response(code, request=_REQ)
            cls = anthropic.InternalServerError if code == 500 else anthropic.BadRequestError
            msg = "boom"
            raise cls(msg, response=response, body=None)
        blocks: list[SimpleNamespace] = [SimpleNamespace(type="text", text="thinking")]
        if kind == "ok":
            blocks.append(SimpleNamespace(type="tool_use", input=step.tool_input))
        elif kind == "malformed":
            blocks.append(SimpleNamespace(type="tool_use", input="not { json"))
        elif kind == "wrong_shape":
            blocks.append(SimpleNamespace(type="tool_use", input=[1, 2]))
        elif kind == "schema_violation":
            blocks.append(SimpleNamespace(type="tool_use", input=dict(BAD_SHAPE)))
        # "empty": text only, no tool call at all
        attrs: dict[str, Any] = {"content": blocks}
        if step.tokens is not None:
            attrs["usage"] = SimpleNamespace(
                input_tokens=step.tokens[0],
                output_tokens=step.tokens[1],
                cache_creation_input_tokens=None,
                cache_read_input_tokens=None,
            )
        return SimpleNamespace(**attrs)


# --------------------------------------------------------------------------- Ollama
class OllamaHarness:
    name = "ollama"
    _SLOW_S = 0.4
    _TIMEOUT_S = 0.15

    def __init__(self) -> None:
        self.attempts = 0
        self.sent: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self._steps: list[Step] = []
        self._server: ThreadingHTTPServer | None = None

    def build(self, *steps: Step) -> Provider:
        self._steps = list(steps)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append(body)
                owner.sent.extend(m["content"] for m in body["messages"])
                step = _step_at(owner._steps, owner.attempts)
                owner.attempts += 1
                status, payload = owner._answer(step)
                try:
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:  # the client already gave up (timeout step)
                    pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{self._server.server_address[1]}"
        settings = OllamaSettings(
            base_url=url, timeout_s=self._TIMEOUT_S, max_retries=2, backoff_s=0
        )
        return OllamaProvider(settings, sleep=lambda _s: None)

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def _answer(self, step: Step) -> tuple[int, bytes]:
        kind = step.kind
        if kind == "timeout":
            time.sleep(self._SLOW_S)
        if kind in {"unavailable", "server_error"}:
            return (503 if kind == "unavailable" else 500), b"{}"
        if kind == "bad_status":
            return 400, b"{}"
        content = {
            "ok": json.dumps(step.tool_input),
            "timeout": json.dumps(step.tool_input),
            "empty": "  ",
            "malformed": "not { json",
            "wrong_shape": "[1, 2]",
            "schema_violation": json.dumps(BAD_SHAPE),
        }[kind]
        envelope: dict[str, Any] = {"message": {"role": "assistant", "content": content}}
        if step.tokens is not None:
            envelope["prompt_eval_count"], envelope["eval_count"] = step.tokens
        return 200, json.dumps(envelope).encode()


HARNESSES: dict[str, type[Harness]] = {"claude": ClaudeHarness, "ollama": OllamaHarness}
