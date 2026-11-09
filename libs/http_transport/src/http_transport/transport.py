"""Plain stdlib HTTP, injectable so tests need no socket."""

from __future__ import annotations

__arbor__ = {"ring": "libs"}

import http.client
import urllib.parse
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)  # names lower-cased


class Getter(Protocol):
    def get(self, url: str, *, timeout_s: float) -> HttpResponse:
        """GET `url`. Raise `OSError` (including `TimeoutError`) on network trouble."""
        ...


class Poster(Protocol):
    def post(
        self, url: str, body: bytes, *, timeout_s: float, content_type: str = "application/json"
    ) -> HttpResponse:
        """POST `body`. Raise `OSError` (including `TimeoutError`) on network trouble."""
        ...


class UrllibTransport:
    """`http.client`: no redirects, no proxies, no scheme surprises. Implements `Getter` and
    `Poster`. A scheme other than http or https is refused."""

    def get(self, url: str, *, timeout_s: float) -> HttpResponse:
        return self._request("GET", url, None, {"Accept": "application/json"}, timeout_s)

    def post(
        self, url: str, body: bytes, *, timeout_s: float, content_type: str = "application/json"
    ) -> HttpResponse:
        return self._request("POST", url, body, {"Content-Type": content_type}, timeout_s)

    @staticmethod
    def _request(
        method: str, url: str, body: bytes | None, headers: dict[str, str], timeout_s: float
    ) -> HttpResponse:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in {"http", "https"}:
            msg = "only http and https URLs are allowed"
            raise OSError(msg)
        conn_type = (
            http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        )
        conn = conn_type(parts.hostname or "", parts.port, timeout=timeout_s)
        try:
            target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            conn.request(method, target, body=body, headers=headers)
            resp = conn.getresponse()
            return HttpResponse(
                resp.status, resp.read(), {name.lower(): value for name, value in resp.getheaders()}
            )
        finally:
            conn.close()
