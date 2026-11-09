"""`EventSource` over the Discovery API.

The city, region and categories are this source's own configuration (a feed source would have a
URL instead); the only thing it is asked per call is a window of dates. A window is split into
searches small enough that the API's paging cap (the first 1,000 results of a search) cannot hide
events: a search with more than 1,000 matches is halved until it fits or is a single day. A single
day that still exceeds it is fetched as far as the cap allows and counted in `truncated`, so the
loss is reported rather than silent.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

from last_newsletter_adapter_ticketmaster.mapping import SOURCE, candidate_from_event
from last_newsletter_core.event_ports import SourceBatch, SourceReport

if TYPE_CHECKING:
    from datetime import datetime

    from last_newsletter_adapter_ticketmaster.client import TicketmasterClient
    from last_newsletter_core.event_ports import SourceWindow
    from last_newsletter_core.events import EventCandidate

RESULT_CAP = 1000  # the API serves at most size x page = 1,000 results of one search
_WINDOW_DAYS = 14
_CLASSIFICATIONS = {"music": "music"}


@dataclass(frozen=True, slots=True)
class TicketmasterConfig:
    city: str
    region: str = ""  # state or province code, e.g. "CA"
    country: str = "US"
    categories: tuple[str, ...] = ("music",)
    dma_id: str = ""  # a Designated Market Area, e.g. "324" for Los Angeles; widens a city search
    page_size: int = 200


@dataclass(slots=True)
class _Counts:
    seen: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    outside_window: int = 0
    truncated: int = 0  # matches beyond the paging cap in a single day (not fetched)
    counted: set[str] = field(default_factory=set)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


@dataclass(slots=True)
class _Run:
    """Everything one `fetch` accumulates: what to keep, what was seen, what was left out."""

    window: SourceWindow
    now: datetime
    categories: frozenset[str]
    found: dict[str, EventCandidate] = field(default_factory=dict)
    counts: _Counts = field(default_factory=_Counts)


class TicketmasterEventSource:
    def __init__(self, client: TicketmasterClient, config: TicketmasterConfig) -> None:
        self._client = client
        self._config = config

    @property
    def name(self) -> str:
        return SOURCE

    def fetch(self, window: SourceWindow, *, now: datetime) -> SourceBatch:
        run = _Run(window, now, frozenset(c.lower() for c in self._config.categories))
        requests_before = self._client.requests
        pending = list(_windows(window.date_from, window.date_to))
        while pending:
            start, end = pending.pop()
            first = self._page(start, end, page=0)
            total = _total(first)
            if total > RESULT_CAP and start < end:
                middle = start + (end - start) // 2
                pending.extend([(middle + timedelta(days=1), end), (start, middle)])
                continue
            for raw in self._pages(start, end, first, total, run.counts):
                _take(raw, run)
        counts = run.counts
        report = SourceReport(
            requests=self._client.requests - requests_before,
            seen=counts.seen,
            skipped=counts.skipped,
            outside_window=counts.outside_window,
            truncated=counts.truncated,
        )
        found = sorted(run.found.values(), key=lambda c: (_day(c), c.message_id))
        return SourceBatch(found, report)

    def _pages(
        self, start: date, end: date, first: dict[str, object], total: int, counts: _Counts
    ) -> list[dict[str, object]]:
        counts.truncated += max(total - RESULT_CAP, 0)
        pages = math.ceil(min(total, RESULT_CAP) / self._config.page_size)
        raws = _events(first)
        for page in range(1, pages):
            raws.extend(_events(self._page(start, end, page=page)))
        return raws

    def _page(self, start: date, end: date, *, page: int) -> dict[str, object]:
        config = self._config
        params = {
            "city": config.city,
            "countryCode": config.country,
            "startDateTime": f"{start.isoformat()}T00:00:00Z",
            # Local evening events fall on the next UTC day, so ask a day past the end and trim.
            "endDateTime": f"{(end + timedelta(days=1)).isoformat()}T23:59:59Z",
            "sort": "date,asc",
            "size": str(config.page_size),
            "page": str(page),
            "locale": "*",
        }
        if config.region:
            params["stateCode"] = config.region
        classes = [_CLASSIFICATIONS.get(c.lower(), c) for c in config.categories]
        if classes:
            params["classificationName"] = ",".join(classes)
        if config.dma_id:
            params["dmaId"] = config.dma_id
        return self._client.get_page(params)


def _take(raw: dict[str, object], run: _Run) -> None:
    counts = run.counts
    # Window edges overlap by design, so the same event can come back; count each once.
    event_id = str(raw.get("id", ""))
    if event_id and event_id in counts.counted:
        return
    counts.counted.add(event_id)
    counts.seen += 1
    outcome = candidate_from_event(raw, now=run.now, categories=run.categories)
    if isinstance(outcome, str):
        counts.skip(outcome)
        return
    if not run.window.date_from <= _day(outcome) <= run.window.date_to:
        counts.outside_window += 1  # the request window is widened; trim to the ask
        return
    run.found.setdefault(outcome.message_id, outcome)


def _windows(first: date, last: date) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    cursor = first
    while cursor <= last:
        end = min(cursor + timedelta(days=_WINDOW_DAYS - 1), last)
        out.append((cursor, end))
        cursor = end + timedelta(days=1)
    return out


def _total(page: dict[str, object]) -> int:
    info = page.get("page")
    value = info.get("totalElements") if isinstance(info, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _events(page: dict[str, object]) -> list[dict[str, object]]:
    embedded = page.get("_embedded")
    raws = embedded.get("events") if isinstance(embedded, dict) else None
    if not isinstance(raws, list):
        return []
    return [{str(k): v for k, v in item.items()} for item in raws if isinstance(item, dict)]


def _day(candidate: EventCandidate) -> date:
    when = candidate.when
    if when is None or when.year is None or when.month is None or when.day is None:
        return date.min
    return date(when.year, when.month, when.day)
