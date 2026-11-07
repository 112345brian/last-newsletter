"""Plain stdlib HTTP POST used by HTTP-speaking providers; injectable so tests need no socket."""

from __future__ import annotations

__arbor__ = {"ring": "llm"}

import http.client
import urllib.parse
from typing import Protocol


class Transport(Protocol):
    def post(self, url: str, body: bytes, *, timeout_s: float) -> tuple[int, bytes]:
        """POST JSON, return (status, body). Raise TimeoutError / OSError on network trouble."""
        ...


class UrllibTransport:
    """`http.client`: no redirects, no proxies, no scheme surprises."""

    def post(self, url: str, body: bytes, *, timeout_s: float) -> tuple[int, bytes]:
        parts = urllib.parse.urlsplit(url)
        conn_type = (
            http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        )
        conn = conn_type(parts.hostname or "", parts.port, timeout=timeout_s)
        try:
            conn.request(
                "POST", parts.path or "/", body=body, headers={"Content-Type": "application/json"}
            )
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()
