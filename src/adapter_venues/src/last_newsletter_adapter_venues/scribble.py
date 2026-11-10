"""Scribble (Highland Park): the venue's own website reads its programme from a public Sanity
content API, and this reads the same one.

Things worth knowing, all observed on the live API:
- it is the site's CMS query endpoint, not a published API: it has no stated terms or stability
  promise and can change without notice, so it is read gently (a page of 100 per request);
- `date` is an ISO instant in UTC ("2026-11-11T03:30:00.000Z"), shown here in the configured zone;
- the programme mixes music, comedy and workshops and carries **no category field**, so nothing
  here can tell them apart: every upcoming event is returned, whatever it is;
- there is no venue field (Scribble is the venue), no ticket link, and the public page address is
  not in the data, so events carry no `url`.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from datetime import time as clock_time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from last_newsletter_adapter_venues.common import clean, day_of
from last_newsletter_core.event_ports import SourceBatch, SourceFetchError, SourceReport
from last_newsletter_core.events import (
    EntityRef,
    EntityRole,
    EventCandidate,
    EventKind,
    PartialWhen,
)

if TYPE_CHECKING:
    from last_newsletter_adapter_venues.client import JsonClient
    from last_newsletter_core.event_ports import SourceWindow

_PAGE = 100
_MAX_PAGES = 5
_SUMMARY_CHARS = 280
_QUERY = (
    '*[_type == "scribbleEvent" && dateTime(date) >= dateTime(now())] | order(date asc)'
    '{_id, title, date, "slug": slug.current, _updatedAt, "description": pt::text(overview)}'
    "[{start}...{end}]"
)


@dataclass(frozen=True, slots=True)
class ScribbleConfig:
    name: str = "scribble"
    project_id: str = "59zw0zbs"
    dataset: str = "production"
    api_version: str = "v2024-07-01"
    venue: str = "Scribble"
    tz: str = "America/Los_Angeles"

    @property
    def url(self) -> str:
        return (
            f"https://{self.project_id}.apicdn.sanity.io/{self.api_version}"
            f"/data/query/{self.dataset}"
        )


def _instant(value: object, tz: tzinfo) -> datetime | None:
    try:
        return datetime.fromisoformat(clean(value)).astimezone(tz)
    except ValueError:
        return None


def candidate_from_event(
    raw: dict[str, object], config: ScribbleConfig, tz: ZoneInfo, now: datetime
) -> EventCandidate | str:
    """The candidate, or a short skip reason: "no_id", "no_title" or "bad_date"."""
    event_id, title = clean(raw.get("_id")), clean(raw.get("title"))
    if not event_id:
        return "no_id"
    if not title:
        return "no_title"
    start = _instant(raw.get("date"), tz)
    if start is None:
        return "bad_date"
    when_time = clock_time(start.hour, start.minute)
    updated = _instant(raw.get("_updatedAt"), UTC)
    return EventCandidate(
        message_id=f"{config.name}:{event_id}",
        title=title,
        kind=EventKind.EVENT,
        summary=clean(raw.get("description"))[:_SUMMARY_CHARS],
        when=PartialWhen(
            year=start.year,
            month=start.month,
            day=start.day,
            time=when_time,
            tz=tz.key,
            raw_text=start.date().isoformat(),
        ),
        evidence=(
            f"{config.name} {event_id} | {title} | {start.date().isoformat()} "
            f"{when_time.isoformat(timespec='minutes')} | {config.venue}"
        ),
        entities=(EntityRef(name=config.venue, role=EntityRole.VENUE),) if config.venue else (),
        uid=f"{config.name}:{event_id}",
        sequence=int(updated.timestamp()) if updated else int(now.timestamp()),
    )


class ScribbleEventSource:
    def __init__(self, client: JsonClient, config: ScribbleConfig | None = None) -> None:
        self._client = client
        self._config = config or ScribbleConfig()
        self._tz = ZoneInfo(self._config.tz)

    @property
    def name(self) -> str:
        return self._config.name

    def fetch(self, window: SourceWindow, *, now: datetime) -> SourceBatch:
        requests_before = self._client.requests
        found: dict[str, EventCandidate] = {}
        skipped: dict[str, int] = {}
        outside = seen = 0
        for raw in self._events():
            seen += 1
            outcome = candidate_from_event(raw, self._config, self._tz, now)
            if isinstance(outcome, str):
                skipped[outcome] = skipped.get(outcome, 0) + 1
            elif not window.date_from <= day_of(outcome) <= window.date_to:
                outside += 1
            else:
                found.setdefault(outcome.message_id, outcome)
        report = SourceReport(
            requests=self._client.requests - requests_before,
            seen=seen,
            skipped=skipped,
            outside_window=outside,
        )
        return SourceBatch(sorted(found.values(), key=lambda c: (day_of(c), c.message_id)), report)

    def _events(self) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        for page in range(_MAX_PAGES):
            query = _QUERY.replace("{start}", str(page * _PAGE)).replace(
                "{end}", str((page + 1) * _PAGE)
            )
            body, _ = self._client.get(self._config.url, {"query": query})
            result = body.get("result") if isinstance(body, dict) else None
            if not isinstance(result, list):
                msg = "the Scribble feed had no result list"
                raise SourceFetchError(msg)
            batch = [{str(k): v for k, v in x.items()} for x in result if isinstance(x, dict)]
            events += batch
            if len(batch) < _PAGE:
                break
        return events
