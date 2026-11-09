"""Rate-limited, key-safe access to the Discovery API's `events.json`, over `httpx`.

Defaults the API publishes: about 5 requests per second and 5,000 per day per key. The client
stays under the per-second limit by spacing requests, retries with `tenacity`, honours
`Rate-Limit-Reset` after a 429, and gives up (rather than sleeping for hours) when the wait is
long, which means the daily quota is spent. The API key is sent as a query parameter, so no
error message, log line or exception text here may contain the request URL: every message is
built from status codes and fixed words, and `httpx` errors are reported by type only.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import time
from typing import TYPE_CHECKING

import httpx
from tenacity import RetryCallState, Retrying, retry_if_exception_type, stop_after_attempt

from last_newsletter_core.event_ports import SourceFetchError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

BASE_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
MIN_INTERVAL_S = 0.25  # 4 requests/second, under the published 5
MAX_ATTEMPTS = 4
MAX_WAIT_S = 60.0  # longer than this after a 429 means the daily quota is spent
_BACKOFF_S = (1.0, 2.0, 4.0)
_PAD_429_S = 0.5
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


class _RetryError(Exception):
    """Try again after `wait` seconds (`None`: the default backoff), plus `pad`."""

    def __init__(self, message: str, *, wait: float | None = None, pad: float = 0.0) -> None:
        super().__init__(message)
        self.message = message
        self.wait = wait
        self.pad = pad


def _wait_for(state: RetryCallState) -> float:
    outcome = state.outcome
    error = outcome.exception() if outcome is not None else None
    if not isinstance(error, _RetryError):
        return 0.0
    base = error.wait if error.wait is not None else _BACKOFF_S[min(state.attempt_number - 1, 2)]
    return base + error.pad


class TicketmasterClient:
    def __init__(
        self,
        api_key: str,
        *,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if not api_key.strip():
            msg = "the Ticketmaster API key is empty"
            raise SourceFetchError(msg)
        self._key = api_key.strip()
        self._http = http or httpx.Client(timeout=_TIMEOUT_S, follow_redirects=False)
        self._sleep = sleep
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._last_request: float | None = None
        self.requests = 0

    def get_page(self, params: Mapping[str, str]) -> dict[str, object]:
        """One page of events. Raises `SourceFetchError` with a key-free message on any failure."""
        retrying = Retrying(
            stop=stop_after_attempt(MAX_ATTEMPTS),
            wait=_wait_for,
            retry=retry_if_exception_type(_RetryError),
            sleep=self._sleep,
            reraise=True,
        )
        try:
            return retrying(self._attempt, params)
        except _RetryError as exhausted:
            raise SourceFetchError(exhausted.message) from None

    def _attempt(self, params: Mapping[str, str]) -> dict[str, object]:
        response = self._send({**params, "apikey": self._key})
        status = response.status_code
        if status == _OK:
            return self._decode(response)
        if status in _AUTH_FAILED:
            msg = f"Ticketmaster rejected the API key (HTTP {status})"
            raise SourceFetchError(msg)
        if status == _TOO_MANY:
            wait = self._reset_wait(response)
            if wait is not None and wait > MAX_WAIT_S:
                msg = (
                    "Ticketmaster rate limit reached and it resets in "
                    f"{wait / 60:.0f} minute(s): the daily quota is probably spent"
                )
                raise SourceFetchError(msg)
            msg = "Ticketmaster kept answering HTTP 429 (too many requests)"
            raise _RetryError(msg, wait=wait, pad=_PAD_429_S)
        msg = f"Ticketmaster answered HTTP {status}"
        if status >= _SERVER_ERROR:
            raise _RetryError(msg)
        raise SourceFetchError(msg)

    def _send(self, params: dict[str, str]) -> httpx.Response:
        if self._last_request is not None:
            gap = self._monotonic() - self._last_request
            if gap < MIN_INTERVAL_S:
                self._sleep(MIN_INTERVAL_S - gap)
        self._last_request = self._monotonic()
        self.requests += 1
        try:
            return self._http.get(BASE_URL, params=params)
        except httpx.HTTPError as error:
            # The error text can embed the URL, and so the key: report only its type.
            msg = f"could not reach Ticketmaster ({type(error).__name__})"
            raise SourceFetchError(msg) from None

    def _reset_wait(self, response: httpx.Response) -> float | None:
        header = response.headers.get("rate-limit-reset")
        if header is None:
            return None
        return parse_reset_seconds(header, now_epoch=self._wall_clock())

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, object]:
        try:
            data = response.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            msg = "Ticketmaster returned a response that is not JSON"
            raise SourceFetchError(msg)
        return {str(key): value for key, value in data.items()}
