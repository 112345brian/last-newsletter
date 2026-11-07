from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

import pytest

from last_newsletter_adapter_events import (
    ModelOutputError,
    ModelProtocolError,
    ModelTimeoutError,
    ModelUnavailableError,
    OllamaClient,
    OllamaConfig,
)
from last_newsletter_adapter_events.schema import EVENT_SCHEMA

from .conftest import ScriptedTransport, answer, client_for, envelope

if TYPE_CHECKING:
    from collections.abc import Iterator


def _chat(client: OllamaClient) -> str:
    return client.chat(system="s", user="u", schema=EVENT_SCHEMA)


def test_request_shape() -> None:
    t = ScriptedTransport(answer())
    _chat(client_for(t, think=False))
    req = t.requests[0]
    assert req["url"] == "http://localhost:11434/api/chat"
    body = req["body"]
    assert body["stream"] is False
    assert body["format"] == EVENT_SCHEMA
    assert body["options"]["temperature"] == 0
    assert "tools" not in body
    assert body["think"] is False
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_timeout_then_success() -> None:
    t = ScriptedTransport(TimeoutError(), answer())
    assert json.loads(_chat(client_for(t)))["events"] == []
    assert len(t.requests) == 2


def test_timeout_every_time_is_typed() -> None:
    t = ScriptedTransport(TimeoutError())
    with pytest.raises(ModelTimeoutError):
        _chat(client_for(t, max_retries=1))
    assert len(t.requests) == 2


def test_connection_refused_is_typed_after_bounded_retries() -> None:
    t = ScriptedTransport(ConnectionRefusedError())
    with pytest.raises(ModelUnavailableError):
        _chat(client_for(t, max_retries=3))
    assert len(t.requests) == 4


def test_http_503_retried_then_ok() -> None:
    t = ScriptedTransport((503, b"busy"), answer())
    _chat(client_for(t))
    assert len(t.requests) == 2


def test_http_404_not_retried() -> None:
    t = ScriptedTransport((404, b"model not found"))
    with pytest.raises(ModelProtocolError):
        _chat(client_for(t))
    assert len(t.requests) == 1


@pytest.mark.parametrize("raw", [b"not json", b"{}", b'{"message": 3}'])
def test_bad_envelope(raw: bytes) -> None:
    with pytest.raises(ModelProtocolError):
        _chat(client_for(ScriptedTransport(raw)))


@pytest.mark.parametrize("content", ["", "   \n"])
def test_empty_output(content: str) -> None:
    with pytest.raises(ModelOutputError):
        _chat(client_for(ScriptedTransport(envelope(content))))


class _Handler(BaseHTTPRequestHandler):
    mode = "ok"

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers["Content-Length"]))
        if self.mode == "slow":
            threading.Event().wait(1.5)
        data = answer()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def server() -> Iterator[tuple[type[_Handler], str]]:
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield _Handler, f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def test_real_urllib_against_fake_server(server: tuple[type[_Handler], str]) -> None:
    handler, url = server
    handler.mode = "ok"
    client = OllamaClient(OllamaConfig(model="m", base_url=url, timeout_s=5))
    assert "events" in _chat(client)


def test_real_urllib_timeout(server: tuple[type[_Handler], str]) -> None:
    handler, url = server
    handler.mode = "slow"
    cfg = OllamaConfig(model="m", base_url=url, timeout_s=0.2, max_retries=0)
    with pytest.raises(ModelTimeoutError):
        _chat(OllamaClient(cfg))


def test_real_urllib_nothing_listening() -> None:
    cfg = OllamaConfig(model="m", base_url="http://127.0.0.1:9", timeout_s=1, max_retries=0)
    with pytest.raises(ModelUnavailableError):
        _chat(OllamaClient(cfg, sleep=lambda _s: None))
