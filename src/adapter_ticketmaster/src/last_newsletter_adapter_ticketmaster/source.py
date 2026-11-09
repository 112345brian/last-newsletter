"""`EventSource` over the Discovery API.

A query is split into windows small enough that the API's paging cap (the first 1,000 results of
a search) cannot hide events: a window with more than 1,000 matches is halved until it fits or is
a single day. A single day that still exceeds the cap is fetched as far as the cap allows and
counted in `FetchStats.truncated`, so the loss is reported rather than silent.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

from last_newsletter_adapter_ticketmaster.mapping import SOURCE, candidate_from_event

if TYPE_CHECKING:
    from datetime import datetime

    from last_newsletter_adapter_ticketmaster.client import TicketmasterClient
    from last_newsletter_core.event_ports import SourceQuery
    from last_newsletter_core.events import EventCandidate

RESULT_CAP = 1000  # the API serves at most size x page = 1,000 results of one search
_WINDOW_DAYS = 14
_CLASSIFICATIONS = {"music": "music"}


@dataclass(frozen=True, slots=True)
class TicketmasterConfig:
    dma_id: str = ""  # a Designated Market Area, e.g. "324" for Los Angeles; widens a city search
    page_size: int = 200


@dataclass(slots=True)
class FetchStats:
    requests: int = 0
    seen: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    outside_window: int = 0
    truncated: int = 0  # matches beyond the paging cap in a single day (not fetched)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


class TicketmasterEventSource:
    def __init__(
        self, client: TicketmasterClient, config: TicketmasterConfig | None = None
    ) -> None:
        self._client = client
        self._config = config or TicketmasterConfig()
        self.stats = FetchStats()
        self._counted: set[str] = set()

    @property
    def name(self) -> str:
        return SOURCE

    def fetch(self, query: SourceQuery, *, now: datetime) -> list[EventCandidate]:
        self.stats = FetchStats()
        self._counted = set()
        categories = frozenset(c.lower() for c in query.categories)
        found: dict[str, EventCandidate] = {}
        pending = list(_windows(query.date_from, query.date_to))
        while pending:
            start, end = pending.pop()
            first = self._page(query, start, end, page=0)
            total = _total(first)
            if total > RESULT_CAP and start < end:
                middle = start + (end - start) // 2
                pending.extend([(middle + timedelta(days=1), end), (start, middle)])
                continue
            for raw in self._pages(query, start, end, first, total):
                self._take(raw, query, now, categories, found)
        return sorted(found.values(), key=lambda c: (_day(c), c.message_id))

    def _pages(
        self, query: SourceQuery, start: date, end: date, first: dict[str, object], total: int
    ) -> list[dict[str, object]]:
        self.stats.truncated += max(total - RESULT_CAP, 0)
        pages = math.ceil(min(total, RESULT_CAP) / self._config.page_size)
        raws = _events(first)
        for page in range(1, pages):
            raws.extend(_events(self._page(query, start, end, page=page)))
        return raws

    def _take(
        self,
        raw: dict[str, object],
        query: SourceQuery,
        now: datetime,
        categories: frozenset[str],
        found: dict[str, EventCandidate],
    ) -> None:
        # Window edges overlap by design, so the same event can come back; count each once.
        event_id = str(raw.get("id", ""))
        if event_id and event_id in self._counted:
            return
        self._counted.add(event_id)
        self.stats.seen += 1
        outcome = candidate_from_event(raw, now=now, categories=categories)
        if isinstance(outcome, str):
            self.stats.skip(outcome)
            return
        day = _day(outcome)
        if not query.date_from <= day <= query.date_to:
            self.stats.outside_window += 1  # the request window is widened; trim to the ask
            return
        found.setdefault(outcome.message_id, outcome)

    def _page(self, query: SourceQuery, start: date, end: date, *, page: int) -> dict[str, object]:
        params = {
            "city": query.city,
            "countryCode": query.country,
            "startDateTime": f"{start.isoformat()}T00:00:00Z",
            # Local evening events fall on the next UTC day, so ask a day past the end and trim.
            "endDateTime": f"{(end + timedelta(days=1)).isoformat()}T23:59:59Z",
            "sort": "date,asc",
            "size": str(self._config.page_size),
            "page": str(page),
            "locale": "*",
        }
        if query.region:
            params["stateCode"] = query.region
        classes = [_CLASSIFICATIONS.get(c.lower(), c) for c in query.categories]
        if classes:
            params["classificationName"] = ",".join(classes)
        if self._config.dma_id:
            params["dmaId"] = self._config.dma_id
        result = self._client.get_page(params)
        self.stats.requests = self._client.requests
        return result


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
