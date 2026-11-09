"""Plain access to Frequent Flyer's keyless JSON API, over `httpx`.

The API allows 60 requests per window and a run uses a handful, so there is no retry loop here:
a 429 or a server error is reported (with the reset time when the API gives one) and a rerun is
safe because ingest is idempotent. Redirects are not followed.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import time
from typing import TYPE_CHECKING

import httpx

from last_newsletter_core.event_ports import SourceFetchError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

BASE_URL = "https://frequentflyerla.com/api/v1/events"
_TIMEOUT_S = 20.0
_OK = 200
_TOO_MANY = 429


class FrequentFlyerClient:
    def __init__(
        self, *, http: httpx.Client | None = None, wall_clock: Callable[[], float] = time.time
    ) -> None:
        self._http = http or httpx.Client(timeout=_TIMEOUT_S, follow_redirects=False)
        self._wall_clock = wall_clock
        self.requests = 0

    def get_events(self, params: Mapping[str, str]) -> dict[str, object]:
        """One response. Raises `SourceFetchError` with a short, URL-free message on any failure."""
        self.requests += 1
        try:
            response = self._http.get(BASE_URL, params=dict(params))
        except httpx.HTTPError as error:
            msg = f"could not reach Frequent Flyer ({type(error).__name__})"
            raise SourceFetchError(msg) from None
        if response.status_code == _TOO_MANY:
            msg = f"Frequent Flyer rate limit reached{self._reset_hint(response)}"
            raise SourceFetchError(msg)
        if response.status_code != _OK:
            msg = f"Frequent Flyer answered HTTP {response.status_code}"
            raise SourceFetchError(msg)
        try:
            data = response.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            msg = "Frequent Flyer returned a response that is not JSON"
            raise SourceFetchError(msg)
        return {str(key): value for key, value in data.items()}

    def _reset_hint(self, response: httpx.Response) -> str:
        try:
            reset = float(response.headers.get("x-ratelimit-reset", ""))
        except ValueError:
            return ""
        wait = max(reset - self._wall_clock(), 0.0)
        return f"; it resets in about {wait:.0f} second(s)"
