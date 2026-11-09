"""`EventSource` over one Squarespace events page.

A venue or promoter becomes a source by configuration: a stable `name` (it labels the mentions),
the events page `url`, the zone its times are shown in, and either the `venue` the whole feed is
held at or the `organizer` whose feed it is (a promoter who books various rooms). The page lists
its upcoming events in full; the past ones are ignored.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from last_newsletter_adapter_squarespace.mapping import FeedContext, candidate_from_item
from last_newsletter_core.event_ports import SourceBatch, SourceFetchError, SourceReport

if TYPE_CHECKING:
    from datetime import datetime

    from last_newsletter_adapter_squarespace.client import SquarespaceClient
    from last_newsletter_core.event_ports import SourceWindow
    from last_newsletter_core.events import EventCandidate


@dataclass(frozen=True, slots=True)
class SquarespaceConfig:
    name: str
    url: str
    tz: str = "America/Los_Angeles"
    venue: str = ""  # the room, when the whole feed is one room's calendar
    organizer: str = ""  # the promoter, when the shows are at various places


class SquarespaceEventSource:
    def __init__(self, client: SquarespaceClient, config: SquarespaceConfig) -> None:
        self._client = client
        self._config = config
        self._tz = ZoneInfo(config.tz)
        parts = urlsplit(config.url)
        self._base = f"{parts.scheme}://{parts.netloc}"

    @property
    def name(self) -> str:
        return self._config.name

    def fetch(self, window: SourceWindow, *, now: datetime) -> SourceBatch:
        requests_before = self._client.requests
        body = self._client.get_page(self._config.url)
        upcoming = body.get("upcoming")
        if not isinstance(upcoming, list):
            msg = "the page has no list of upcoming events (is it a Squarespace events page?)"
            raise SourceFetchError(msg)
        feed = FeedContext(
            name=self._config.name,
            base_url=self._base,
            tz=self._tz,
            now=now,
            venue=self._config.venue,
            organizer=self._config.organizer,
        )
        found: dict[str, EventCandidate] = {}
        skipped: dict[str, int] = {}
        outside = seen = 0
        for raw in upcoming:
            if not isinstance(raw, dict):
                continue
            seen += 1
            outcome = candidate_from_item({str(k): v for k, v in raw.items()}, feed)
            if isinstance(outcome, str):
                skipped[outcome] = skipped.get(outcome, 0) + 1
                continue
            if not window.date_from <= _day(outcome) <= window.date_to:
                outside += 1
            else:
                found.setdefault(outcome.message_id, outcome)
        report = SourceReport(
            requests=self._client.requests - requests_before,
            seen=seen,
            skipped=skipped,
            outside_window=outside,
        )
        ordered = sorted(found.values(), key=lambda c: (_day(c), c.message_id))
        return SourceBatch(ordered, report)


def _day(candidate: EventCandidate) -> date:
    when = candidate.when
    if when is None or when.year is None or when.month is None or when.day is None:
        return date.min
    return date(when.year, when.month, when.day)
