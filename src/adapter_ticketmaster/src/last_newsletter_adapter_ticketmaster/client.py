"""Rate-limited, key-safe access to the Discovery API's `events.json`.

Defaults the API publishes: about 5 requests per second and 5,000 per day per key. The client
stays under the per-second limit by spacing requests, honours `Rate-Limit-Reset` after a 429, and
gives up (rather than sleeping for hours) when the wait is long, which means the daily quota is
spent. The API key is sent as a query parameter, so no error message, log line or exception text
here may contain the request URL: every message is built from status codes and fixed words.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import json
import time
import urllib.parse
from typing import TYPE_CHECKING

from http_transport import Getter, HttpResponse, UrllibTransport
from last_newsletter_core.event_ports import SourceFetchError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

BASE_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
MIN_INTERVAL_S = 0.25  # 4 requests/second, under the published 5
MAX_ATTEMPTS = 4
MAX_WAIT_S = 60.0  # longer than this after a 429 means the daily quota is spent
_BACKOFF_S = (1.0, 2.0, 4.0)
_TIMEOUT_S = 20.0
_EPOCH_MS = 1e11
_EPOCH_S = 1e8
_OK = 200
_AUTH_FAILED = (401, 403)
_TOO_MANY = 429
_SERVER_ERROR = 500


def parse_reset_seconds(value: str, *, now_epoch: float) -> float | None:
    """Seconds to wait from a `Rate-Limit-Reset` header. The value may be an epoch in
    milliseconds, an epoch in seconds, or a number of seconds; anything unreadable is None."""
    try:
        number = float(value)
    except ValueError:
        return None
    if number > _EPOCH_MS:
        number = number / 1000.0 - now_epoch
    elif number > _EPOCH_S:
        number -= now_epoch
    return max(number, 0.0)


class TicketmasterClient:
    def __init__(
        self,
        api_key: str,
        *,
        transport: Getter | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if not api_key.strip():
            msg = "the Ticketmaster API key is empty"
            raise SourceFetchError(msg)
        self._key = api_key.strip()
        self._transport = transport or UrllibTransport()
        self._sleep = sleep
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._last_request: float | None = None
        self.requests = 0

    def get_page(self, params: Mapping[str, str]) -> dict[str, object]:
        """One page of events. Raises `SourceFetchError` with a key-free message on any failure."""
        url = f"{BASE_URL}?{urllib.parse.urlencode({**params, 'apikey': self._key})}"
        for attempt in range(MAX_ATTEMPTS):
            response = self._send(url)
            if response.status == _OK:
                return self._decode(response)
            if response.status in _AUTH_FAILED:
                msg = f"Ticketmaster rejected the API key (HTTP {response.status})"
                raise SourceFetchError(msg)
            last = attempt == MAX_ATTEMPTS - 1
            if response.status == _TOO_MANY:
                wait = self._reset_wait(response)
                if wait is not None and wait > MAX_WAIT_S:
                    msg = (
                        "Ticketmaster rate limit reached and it resets in "
                        f"{wait / 60:.0f} minute(s): the daily quota is probably spent"
                    )
                    raise SourceFetchError(msg)
                if last:
                    msg = "Ticketmaster kept answering HTTP 429 (too many requests)"
                    raise SourceFetchError(msg)
                self._sleep((wait if wait is not None else _BACKOFF_S[attempt]) + 0.5)
                continue
            if response.status >= _SERVER_ERROR and not last:
                self._sleep(_BACKOFF_S[attempt])
                continue
            msg = f"Ticketmaster answered HTTP {response.status}"
            raise SourceFetchError(msg)
        msg = "Ticketmaster request failed"  # pragma: no cover - the loop always returns or raises
        raise SourceFetchError(msg)

    def _send(self, url: str) -> HttpResponse:
        if self._last_request is not None:
            gap = self._monotonic() - self._last_request
            if gap < MIN_INTERVAL_S:
                self._sleep(MIN_INTERVAL_S - gap)
        self._last_request = self._monotonic()
        self.requests += 1
        try:
            return self._transport.get(url, timeout_s=_TIMEOUT_S)
        except OSError as error:
            # The error text can embed the URL, and so the key: report only its type.
            msg = f"could not reach Ticketmaster ({type(error).__name__})"
            raise SourceFetchError(msg) from None

    def _reset_wait(self, response: HttpResponse) -> float | None:
        header = response.headers.get("rate-limit-reset")
        if header is None:
            return None
        return parse_reset_seconds(header, now_epoch=self._wall_clock())

    @staticmethod
    def _decode(response: HttpResponse) -> dict[str, object]:
        try:
            data = json.loads(response.body)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            msg = "Ticketmaster returned a response that is not JSON"
            raise SourceFetchError(msg)
        return {str(key): value for key, value in data.items()}
