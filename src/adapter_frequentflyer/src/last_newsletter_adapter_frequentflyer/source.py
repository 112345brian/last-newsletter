"""`EventSource` over Frequent Flyer's API.

The API has no paging (`offset` and `page` are ignored), so a response is complete only when its
`count` equals `total_matching`. Searches are made a week at a time, and one that comes back
short is halved until it fits or is a single day; a single day that is still short is reported
as `truncated` rather than hidden.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from last_newsletter_adapter_frequentflyer.mapping import SOURCE, candidate_from_event
from last_newsletter_core.event_ports import SourceBatch, SourceReport

if TYPE_CHECKING:
    from datetime import datetime

    from last_newsletter_adapter_frequentflyer.client import FrequentFlyerClient
    from last_newsletter_core.event_ports import SourceWindow
    from last_newsletter_core.events import EventCandidate

LIMIT = 100
_WINDOW_DAYS = 7


@dataclass(frozen=True, slots=True)
class FrequentFlyerConfig:
    vibe: str = "music"  # the API's own filter; "" asks for every kind of event
    neighborhood: str = ""  # a slug such as "echo-park"
    curation: str = ""


class FrequentFlyerEventSource:
    def __init__(
        self, client: FrequentFlyerClient, config: FrequentFlyerConfig | None = None
    ) -> None:
        self._client = client
        self._config = config or FrequentFlyerConfig()

    @property
    def name(self) -> str:
        return SOURCE

    def fetch(self, window: SourceWindow, *, now: datetime) -> SourceBatch:
        requests_before = self._client.requests
        found: dict[str, EventCandidate] = {}
        skipped: dict[str, int] = {}
        seen: set[str] = set()
        outside = truncated = 0
        notes: list[str] = []
        pending = list(_windows(window.date_from, window.date_to))
        while pending:
            start, end = pending.pop()
            body = self._client.get_events(self._params(start, end))
            raws = _events(body)
            total = _total(body, len(raws))
            attribution = body.get("attribution")
            if isinstance(attribution, str) and attribution and attribution not in notes:
                notes.append(attribution)
            if len(raws) < total and start < end:
                middle = start + (end - start) // 2
                pending.extend([(middle + timedelta(days=1), end), (start, middle)])
                continue
            truncated += max(total - len(raws), 0)
            city = str(body.get("city") or "")
            for raw in raws:
                event_id = str(raw.get("id", ""))
                if event_id and event_id in seen:
                    continue
                seen.add(event_id)
                outcome = candidate_from_event(raw, now=now, city=city)
                if isinstance(outcome, str):
                    skipped[outcome] = skipped.get(outcome, 0) + 1
                elif _day(outcome) < window.date_from or _day(outcome) > window.date_to:
                    outside += 1
                else:
                    found.setdefault(outcome.message_id, outcome)
        report = SourceReport(
            requests=self._client.requests - requests_before,
            seen=len(seen),
            skipped=skipped,
            outside_window=outside,
            truncated=truncated,
            notes=tuple(notes),
        )
        ordered = sorted(found.values(), key=lambda c: (_day(c), c.message_id))
        return SourceBatch(ordered, report)

    def _params(self, start: date, end: date) -> dict[str, str]:
        params = {"from": start.isoformat(), "to": end.isoformat(), "limit": str(LIMIT)}
        if self._config.vibe:
            params["vibe"] = self._config.vibe
        if self._config.neighborhood:
            params["neighborhood"] = self._config.neighborhood
        if self._config.curation:
            params["curation"] = self._config.curation
        return params


def _windows(first: date, last: date) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    cursor = first
    while cursor <= last:
        end = min(cursor + timedelta(days=_WINDOW_DAYS - 1), last)
        out.append((cursor, end))
        cursor = end + timedelta(days=1)
    return out


def _events(body: dict[str, object]) -> list[dict[str, object]]:
    raws = body.get("events")
    if not isinstance(raws, list):
        return []
    return [{str(k): v for k, v in item.items()} for item in raws if isinstance(item, dict)]


def _total(body: dict[str, object], fallback: int) -> int:
    value = body.get("total_matching")
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback


def _day(candidate: EventCandidate) -> date:
    when = candidate.when
    if when is None or when.year is None or when.month is None or when.day is None:
        return date.min
    return date(when.year, when.month, when.day)
