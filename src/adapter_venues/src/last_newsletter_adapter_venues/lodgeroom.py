"""Lodge Room (Highland Park): its WordPress site publishes every show through the standard REST
API (`/wp-json/wp/v2/shows`) with the details in ACF custom fields.

Things worth knowing, all observed on the live site:
- the endpoint lists **every show ever** (393 at the time of writing, 100 per page), ordered by
  when the *listing* was published, not by show date, so every page is read and upcoming shows are
  picked out here;
- the show date is `acf.date_and_time_of_show`, written "11/18/2026 7:00 pm" in the venue's own
  local time (the top-level `date` is the publish date and must not be used);
- artists are nested post records: `headliner` and `additional_artists` carry `post_title`.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import time as clock
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import time as clock_time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from last_newsletter_adapter_venues.common import clean, day_of, plain
from last_newsletter_core.event_ports import SourceBatch, SourceFetchError, SourceReport
from last_newsletter_core.events import (
    EntityRef,
    EntityRole,
    EventCandidate,
    EventKind,
    PartialWhen,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from last_newsletter_adapter_venues.client import JsonClient
    from last_newsletter_core.event_ports import SourceWindow

SHOWS_URL = "https://www.lodgeroomhlp.com/wp-json/wp/v2/shows"
_FIELDS = "id,link,title,acf,modified_gmt"
_PER_PAGE = 100
_MAX_PAGES = 10
_PAUSE_S = 0.5
_SUMMARY_CHARS = 280


@dataclass(frozen=True, slots=True)
class LodgeRoomConfig:
    name: str = "lodgeroom"
    url: str = SHOWS_URL
    tz: str = "America/Los_Angeles"


def _show_time(text: str, tz: ZoneInfo) -> tuple[datetime, bool] | None:
    """The local date and time, and whether the listing gave a time at all."""
    for pattern, has_time in (("%m/%d/%Y %I:%M %p", True), ("%m/%d/%Y", False)):
        try:
            return datetime.strptime(text.strip(), pattern).replace(tzinfo=tz), has_time
        except ValueError:
            continue
    return None


def _names(value: object) -> list[str]:
    """Artist names from a list of post records (the field is `""` or `False` when empty)."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for entry in value:
        if isinstance(entry, dict):
            out.extend([clean(entry.get("post_title"))] if clean(entry.get("post_title")) else [])
        elif isinstance(entry, list):  # additional_artists nests one more level
            out.extend(_names(entry))
    return out


def _modified(raw: dict[str, object], fallback: int) -> int:
    try:
        stamp = datetime.fromisoformat(clean(raw.get("modified_gmt"))).replace(tzinfo=UTC)
    except ValueError:
        return fallback
    return int(stamp.timestamp())


def candidate_from_show(
    raw: dict[str, object], *, name: str, tz: ZoneInfo, now: datetime
) -> EventCandidate | str:
    """The candidate, or a short skip reason: "no_id", "no_title" or "bad_date"."""
    acf = raw.get("acf")
    fields = {str(k): v for k, v in acf.items()} if isinstance(acf, dict) else {}
    show_id = clean(raw.get("id"))
    title_obj = raw.get("title")
    title = clean(title_obj.get("rendered") if isinstance(title_obj, dict) else title_obj)
    headliners = _names(fields.get("headliner"))
    title = title or " / ".join(headliners)
    if not show_id:
        return "no_id"
    if not title:
        return "no_title"
    parsed = _show_time(clean(fields.get("date_and_time_of_show")), tz)
    if parsed is None:
        return "bad_date"
    moment, has_time = parsed
    when_time = clock_time(moment.hour, moment.minute) if has_time else None
    venue_obj = fields.get("venue")
    venue = clean(venue_obj.get("post_title")) if isinstance(venue_obj, dict) else ""
    entities = [EntityRef(name=n, role=EntityRole.HEADLINER) for n in headliners]
    entities += [
        EntityRef(name=n, role=EntityRole.SUPPORT) for n in _names(fields.get("additional_artists"))
    ]
    if venue:
        entities.append(EntityRef(name=venue, role=EntityRole.VENUE))
    doors = clean(fields.get("door_time"))
    ages = fields.get("ages")
    description = plain(fields.get("show_description"))
    genre = clean(fields.get("genre"))
    day = moment.date().isoformat()
    return EventCandidate(
        message_id=f"{name}:{show_id}",
        title=title,
        kind=EventKind.EVENT,
        summary=(f"Doors {doors}. {description}" if doors else description)[:_SUMMARY_CHARS],
        when=PartialWhen(
            year=moment.year,
            month=moment.month,
            day=moment.day,
            time=when_time,
            tz=tz.key,
            raw_text=clean(fields.get("date_and_time_of_show")),
        ),
        evidence=(
            f"{name} {show_id} | {title} | {day} "
            f"{when_time.isoformat(timespec='minutes') if when_time else 'time tbd'} | {venue}"
        ),
        entities=tuple(entities),
        uid=f"{name}:{show_id}",
        sequence=_modified(raw, int(now.timestamp())),
        url=(
            clean(fields.get("external_ticket_button_url"))
            or clean(fields.get("rsvp_url"))
            or clean(raw.get("link"))
            or None
        ),
        tags=frozenset([genre.lower()]) if genre else frozenset(),
        age=clean(ages.get("label")) if isinstance(ages, dict) else "",
    )


class LodgeRoomEventSource:
    def __init__(
        self,
        client: JsonClient,
        config: LodgeRoomConfig | None = None,
        *,
        sleep: Callable[[float], None] = clock.sleep,
    ) -> None:
        self._client = client
        self._config = config or LodgeRoomConfig()
        self._tz = ZoneInfo(self._config.tz)
        self._sleep = sleep

    @property
    def name(self) -> str:
        return self._config.name

    def fetch(self, window: SourceWindow, *, now: datetime) -> SourceBatch:
        requests_before = self._client.requests
        found: dict[str, EventCandidate] = {}
        skipped: dict[str, int] = {}
        outside = seen = 0
        for raw in self._shows():
            seen += 1
            outcome = candidate_from_show(raw, name=self._config.name, tz=self._tz, now=now)
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

    def _shows(self) -> list[dict[str, object]]:
        shows: list[dict[str, object]] = []
        total_pages = 1
        page = 1
        while page <= min(total_pages, _MAX_PAGES):
            if page > 1:
                self._sleep(_PAUSE_S)
            body, headers = self._client.get(
                self._config.url,
                {"per_page": str(_PER_PAGE), "page": str(page), "_fields": _FIELDS},
            )
            if not isinstance(body, list):
                msg = "the Lodge Room feed was not a list of shows"
                raise SourceFetchError(msg)
            shows += [{str(k): v for k, v in x.items()} for x in body if isinstance(x, dict)]
            total_pages = _int(headers.get("x-wp-totalpages"), 1)
            page += 1
        return shows


def _int(value: str | None, default: int) -> int:
    try:
        return int(value or "")
    except ValueError:
        return default
