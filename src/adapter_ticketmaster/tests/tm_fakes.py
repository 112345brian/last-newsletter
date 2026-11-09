"""Hand-written fakes for the Ticketmaster adapter tests: `httpx.MockTransport` answers, nothing
touches a socket."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable

FIXTURES = Path(__file__).parent / "fixtures"
KEY = "test-key-not-a-real-secret"


def fixture(name: str) -> dict[str, object]:
    data = json.loads((FIXTURES / name).read_text())
    assert isinstance(data, dict)
    return {str(k): v for k, v in data.items()}


def ok(body: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json=body)


def reply(status: int, content: bytes = b"{}", **headers: str) -> httpx.Response:
    return httpx.Response(status, content=content, headers=headers)


def query_of(request: httpx.Request) -> dict[str, str]:
    return dict(request.url.params)


@dataclass
class Scripted:
    """Answers each request with the next scripted response (or raises the next scripted error)."""

    script: list[httpx.Response | Exception]
    requests: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


@dataclass
class Handled:
    """Answers each request by calling `handler` with its decoded query parameters."""

    handler: Callable[[dict[str, str]], httpx.Response]
    queries: list[dict[str, str]] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = query_of(request)
        self.queries.append(params)
        return self.handler(params)

    @property
    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


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
