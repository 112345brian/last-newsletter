"""Hand-written `httpx.MockTransport` fakes for the Frequent Flyer adapter tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict[str, object]:
    data = json.loads((FIXTURES / name).read_text())
    assert isinstance(data, dict)
    return {str(k): v for k, v in data.items()}


def ok(body: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json=body)


@dataclass
class Handled:
    """Answers each request by calling `handler` with its decoded query parameters."""

    handler: Callable[[dict[str, str]], httpx.Response]
    queries: list[dict[str, str]] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.queries.append(params)
        return self.handler(params)

    @property
    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))
