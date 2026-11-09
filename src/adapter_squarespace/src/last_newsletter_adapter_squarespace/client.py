"""Fetches one Squarespace events page as JSON over `httpx`.

Squarespace publishes any page's content as JSON when `?format=json` is added to its URL. Errors
name the status code or exception type only, and the body is capped (these pages carry the whole
site's settings and can be a megabyte or more).
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import json

import httpx

from last_newsletter_core.event_ports import SourceFetchError

MAX_BYTES = 10_000_000
_TIMEOUT_S = 30.0
_MAX_REDIRECTS = 3
_OK = 200


class SquarespaceClient:
    def __init__(self, *, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(
            timeout=_TIMEOUT_S, follow_redirects=True, max_redirects=_MAX_REDIRECTS
        )
        self.requests = 0

    def get_page(self, url: str) -> dict[str, object]:
        """The page's JSON. Raises `SourceFetchError` with a short message on any failure."""
        self.requests += 1
        try:
            with self._http.stream("GET", url, params={"format": "json"}) as response:
                if response.status_code != _OK:
                    msg = f"the events page answered HTTP {response.status_code}"
                    raise SourceFetchError(msg)
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        msg = f"the events page is larger than {MAX_BYTES // 1_000_000} MB"
                        raise SourceFetchError(msg)
        except httpx.HTTPError as error:
            msg = f"could not fetch the events page ({type(error).__name__})"
            raise SourceFetchError(msg) from None
        try:
            data = json.loads(bytes(body))
        except ValueError:
            data = None
        if not isinstance(data, dict):
            msg = "the events page did not return JSON (is it a Squarespace events page?)"
            raise SourceFetchError(msg)
        return {str(key): value for key, value in data.items()}
