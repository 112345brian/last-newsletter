"""`EventSource` over one iCalendar feed URL.

Any published calendar becomes a source by configuration: a stable `name` (it labels the mentions),
the feed `url`, the feed's `tz` (UTC timestamps are shown in it), and optionally a fixed `venue`
for a feed that is one room's calendar. The feed is fetched whole and trimmed to the window, so a
feed with a short horizon ("this weekend") simply returns what it has.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from icalendar import Calendar

from last_newsletter_adapter_ical.mapping import candidate_from_vevent
from last_newsletter_core.event_ports import SourceBatch, SourceFetchError, SourceReport

if TYPE_CHECKING:
    from last_newsletter_adapter_ical.client import IcalClient
    from last_newsletter_core.event_ports import SourceWindow
    from last_newsletter_core.events import EventCandidate


@dataclass(frozen=True, slots=True)
class IcalConfig:
    name: str
    url: str
    tz: str = "America/Los_Angeles"
    venue: str = ""  # set when the whole feed is one venue's calendar


class IcalEventSource:
    def __init__(self, client: IcalClient, config: IcalConfig) -> None:
        self._client = client
        self._config = config
        self._tz = ZoneInfo(config.tz)

    @property
    def name(self) -> str:
        return self._config.name

    def fetch(self, window: SourceWindow, *, now: datetime) -> SourceBatch:
        requests_before = self._client.requests
        text = self._client.get_text(self._config.url)
        try:
            calendar = Calendar.from_ical(text)
        except ValueError:
            msg = "the feed is not a valid iCalendar file"
            raise SourceFetchError(msg) from None
        found: dict[str, EventCandidate] = {}
        skipped: dict[str, int] = {}
        outside = seen = 0
        for event in calendar.walk("VEVENT"):
            seen += 1
            outcome = candidate_from_vevent(
                event, name=self._config.name, tz=self._tz, now=now, venue=self._config.venue
            )
            if isinstance(outcome, str):
                skipped[outcome] = skipped.get(outcome, 0) + 1
                continue
            day = _day(outcome)
            if not window.date_from <= day <= window.date_to:
                outside += 1
            else:
                found.setdefault(outcome.message_id, outcome)
        report = SourceReport(
            requests=self._client.requests - requests_before,
            seen=seen,
            skipped=skipped,
            outside_window=outside,
        )
        return SourceBatch(sorted(found.values(), key=lambda c: (_day(c), c.message_id)), report)


def _day(candidate: EventCandidate) -> date:
    when = candidate.when
    if when is None or when.year is None or when.month is None or when.day is None:
        return date.min
    return date(when.year, when.month, when.day)
