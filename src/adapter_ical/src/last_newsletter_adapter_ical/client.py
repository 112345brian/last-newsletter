"""Fetches one iCalendar feed over `httpx`.

A feed URL can carry a secret token (private calendars do), so no message here contains it: errors
name the status code or the exception type only. Redirects are followed a few hops (feeds move),
and the body is capped so a wrong URL cannot pull in something huge.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import httpx

from last_newsletter_core.event_ports import SourceFetchError

MAX_BYTES = 5_000_000
_TIMEOUT_S = 30.0
_MAX_REDIRECTS = 3
_OK = 200


class IcalClient:
    def __init__(self, *, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(
            timeout=_TIMEOUT_S, follow_redirects=True, max_redirects=_MAX_REDIRECTS
        )
        self.requests = 0

    def get_text(self, url: str) -> str:
        """The feed body as text. Raises `SourceFetchError` with a URL-free message on failure."""
        self.requests += 1
        try:
            with self._http.stream(
                "GET", url, headers={"Accept": "text/calendar, */*"}
            ) as response:
                if response.status_code != _OK:
                    msg = f"the calendar feed answered HTTP {response.status_code}"
                    raise SourceFetchError(msg)
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        msg = f"the calendar feed is larger than {MAX_BYTES // 1_000_000} MB"
                        raise SourceFetchError(msg)
                encoding = response.encoding or "utf-8"
        except httpx.HTTPError as error:
            msg = f"could not fetch the calendar feed ({type(error).__name__})"
            raise SourceFetchError(msg) from None
        return bytes(body).decode(encoding, errors="replace")
