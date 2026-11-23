"""The Last.fm web service over `httpx`: artist tags and a user's top artists.

Only the documented API is used. Every error names what failed (a status code, an exception type,
Last.fm's own error code) and never the request URL, which carries the API key. Requests are paced
(`min_interval_s`) to stay well inside Last.fm's rate limit.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import json
import time
from typing import TYPE_CHECKING, Protocol

import httpx

from lastfm_taste.taste import TasteConfigurationError, TasteSourceError

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = "https://ws.audioscrobbler.com/2.0/"
MAX_BYTES = 5_000_000
_TIMEOUT_S = 20.0
_OK = 200
ERROR_NOT_FOUND = 6  # "the artist/user you supplied could not be found"
_ERROR_TEXT = {
    10: "the Last.fm API key was refused",
    26: "the Last.fm API key is suspended",
    29: "Last.fm is rate limiting this key",
    17: "that Last.fm profile is private",
}


class LastfmNotFoundError(Exception):
    """Last.fm answered "not found" (error 6): the artist or user does not exist there."""


class LastfmApi(Protocol):
    """What the sources need from a Last.fm client: one call that returns the JSON answer."""

    def call(self, method: str, **params: str) -> dict[str, object]:
        """The JSON answer to `method`. Raises `LastfmNotFoundError` or `TasteSourceError`."""
        ...


class LastfmClient:
    def __init__(
        self,
        api_key: str,
        *,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        min_interval_s: float = 0.25,
    ) -> None:
        if not api_key.strip():
            msg = "a Last.fm API key is required"
            raise TasteConfigurationError(msg)
        self._key = api_key.strip()
        self._http = http or httpx.Client(timeout=_TIMEOUT_S)
        self._sleep = sleep
        self._min_interval_s = min_interval_s
        self.requests = 0

    def call(self, method: str, **params: str) -> dict[str, object]:
        """The JSON answer to `method`. Raises `LastfmNotFoundError` or `TasteSourceError`."""
        if self.requests:
            self._sleep(self._min_interval_s)
        self.requests += 1
        query = {"method": method, "api_key": self._key, "format": "json", **params}
        try:
            response = self._http.get(ROOT, params=query)
        except httpx.HTTPError as error:
            msg = f"could not reach Last.fm ({type(error).__name__})"
            raise TasteSourceError(msg) from None
        if len(response.content) > MAX_BYTES:
            msg = "Last.fm sent an unexpectedly large answer"
            raise TasteSourceError(msg)
        data = _parse(response)
        code = data.get("error")
        if code == ERROR_NOT_FOUND:
            raise LastfmNotFoundError
        if code is not None:
            msg = _ERROR_TEXT.get(code if isinstance(code, int) else -1, f"Last.fm error {code}")
            raise TasteSourceError(msg)
        if response.status_code != _OK:
            msg = f"Last.fm answered HTTP {response.status_code}"
            raise TasteSourceError(msg)
        return data


def _parse(response: httpx.Response) -> dict[str, object]:
    try:
        data = json.loads(response.content)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        msg = f"Last.fm answered HTTP {response.status_code} with something that is not JSON"
        raise TasteSourceError(msg)
    return {str(key): value for key, value in data.items()}
