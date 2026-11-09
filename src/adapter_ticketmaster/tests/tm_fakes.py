"""Hand-written transport fakes for the Ticketmaster adapter tests (no sockets, no mocks)."""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from http_transport import HttpResponse

if TYPE_CHECKING:
    from collections.abc import Callable

FIXTURES = Path(__file__).parent / "fixtures"
KEY = "test-key-not-a-real-secret"


def fixture(name: str) -> dict[str, object]:
    data = json.loads((FIXTURES / name).read_text())
    assert isinstance(data, dict)
    return {str(k): v for k, v in data.items()}


def ok(body: dict[str, object]) -> HttpResponse:
    return HttpResponse(200, json.dumps(body).encode())


def query_of(url: str) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


@dataclass
class ScriptedTransport:
    """Answers each request with the next scripted response (or raises the next scripted error)."""

    script: list[HttpResponse | Exception]
    urls: list[str] = field(default_factory=list)

    def get(self, url: str, *, timeout_s: float) -> HttpResponse:
        _ = timeout_s
        self.urls.append(url)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@dataclass
class HandlerTransport:
    """Answers each request by calling `handler` with the decoded query parameters."""

    handler: Callable[[dict[str, str]], HttpResponse]
    queries: list[dict[str, str]] = field(default_factory=list)

    def get(self, url: str, *, timeout_s: float) -> HttpResponse:
        _ = timeout_s
        params = query_of(url)
        self.queries.append(params)
        return self.handler(params)


class Clock:
    """A controllable monotonic and wall clock; `sleep` advances both and records the wait."""

    def __init__(self, wall: float = 1_800_000_000.0) -> None:
        self.mono = 1000.0
        self.wall = wall
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.mono

    def wall_clock(self) -> float:
        return self.wall

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.mono += seconds
        self.wall += seconds
