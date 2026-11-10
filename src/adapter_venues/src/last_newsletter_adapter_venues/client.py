"""Plain JSON GETs over `httpx`, shared by the venue sources.

Errors name the status code or the exception type only (a URL can carry a key or a query worth
keeping out of logs), redirects are followed a few hops, and the body is capped. The response
headers come back with the JSON because WordPress reports its page count in one.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import json
from typing import TYPE_CHECKING

import httpx

from last_newsletter_core.event_ports import SourceFetchError

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_BYTES = 10_000_000
_TIMEOUT_S = 30.0
_MAX_REDIRECTS = 3
_OK = 200


class JsonClient:
    def __init__(self, *, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(
            timeout=_TIMEOUT_S, follow_redirects=True, max_redirects=_MAX_REDIRECTS
        )
        self.requests = 0

    def get(
        self, url: str, params: Mapping[str, str] | None = None
    ) -> tuple[object, dict[str, str]]:
        """The parsed JSON and the response headers (names lower-cased)."""
        self.requests += 1
        try:
            with self._http.stream("GET", url, params=dict(params or {})) as response:
                if response.status_code != _OK:
                    msg = f"the feed answered HTTP {response.status_code}"
                    raise SourceFetchError(msg)
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        msg = f"the feed is larger than {MAX_BYTES // 1_000_000} MB"
                        raise SourceFetchError(msg)
                headers = {name.lower(): value for name, value in response.headers.items()}
        except httpx.HTTPError as error:
            msg = f"could not fetch the feed ({type(error).__name__})"
            raise SourceFetchError(msg) from None
        try:
            return json.loads(bytes(body)), headers
        except ValueError:
            msg = "the feed did not return JSON"
            raise SourceFetchError(msg) from None
