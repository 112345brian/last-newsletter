"""The real transport against a throwaway local HTTP server (no outside network)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

import pytest

from http_transport import UrllibTransport

if TYPE_CHECKING:
    from collections.abc import Iterator


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "/target")
            self.end_headers()
            return
        body = json.dumps({"method": "GET", "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Rate-Limit-Reset", "7")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        body = json.dumps(
            {"method": "POST", "type": self.headers["Content-Type"], "echo": raw.decode()}
        ).encode()
        self.send_response(201)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def base_url() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def test_get_returns_status_body_and_lower_cased_headers(base_url: str) -> None:
    response = UrllibTransport().get(f"{base_url}/events.json?city=LA", timeout_s=5)
    assert response.status == 200
    assert json.loads(response.body) == {"method": "GET", "path": "/events.json?city=LA"}
    assert response.headers["rate-limit-reset"] == "7"
    assert response.headers["content-type"] == "application/json"


def test_post_sends_the_body_with_the_content_type(base_url: str) -> None:
    response = UrllibTransport().post(f"{base_url}/api", b'{"a": 1}', timeout_s=5)
    assert response.status == 201
    assert json.loads(response.body) == {
        "method": "POST",
        "type": "application/json",
        "echo": '{"a": 1}',
    }
    other = UrllibTransport().post(f"{base_url}/api", b"x", timeout_s=5, content_type="text/plain")
    assert json.loads(other.body)["type"] == "text/plain"


def test_a_redirect_is_returned_not_followed(base_url: str) -> None:
    response = UrllibTransport().get(f"{base_url}/redirect", timeout_s=5)
    assert response.status == 302
    assert response.headers["location"] == "/target"


def test_an_empty_path_is_the_root(base_url: str) -> None:
    response = UrllibTransport().get(base_url, timeout_s=5)
    assert json.loads(response.body)["path"] == "/"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "//example.com/x"])
def test_other_schemes_are_refused_before_any_connection(url: str) -> None:
    with pytest.raises(OSError, match="only http and https"):
        UrllibTransport().get(url, timeout_s=1)


def test_a_refused_connection_is_an_oserror() -> None:
    with pytest.raises(ConnectionRefusedError):
        UrllibTransport().get("http://127.0.0.1:9/", timeout_s=1)
