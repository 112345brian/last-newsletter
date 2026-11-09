"""Plain stdlib HTTPS GET, injectable so tests need no socket."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import http.client
import urllib.parse
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)  # lower-cased names


class Transport(Protocol):
    def get(self, url: str, *, timeout_s: float) -> HttpResponse:
        """GET `url`. Raise `OSError` (including `TimeoutError`) on network trouble."""
        ...


class UrllibTransport:
    """`http.client`: HTTPS only, no redirects, no proxies, no scheme surprises."""

    def get(self, url: str, *, timeout_s: float) -> HttpResponse:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https":
            msg = "only https URLs are allowed"
            raise OSError(msg)
        conn = http.client.HTTPSConnection(parts.hostname or "", parts.port, timeout=timeout_s)
        try:
            target = parts.path + (f"?{parts.query}" if parts.query else "")
            conn.request("GET", target or "/", headers={"Accept": "application/json"})
            resp = conn.getresponse()
            headers = {name.lower(): value for name, value in resp.getheaders()}
            return HttpResponse(resp.status, resp.read(), headers)
        finally:
            conn.close()
