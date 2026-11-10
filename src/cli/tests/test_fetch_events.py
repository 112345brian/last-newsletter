"""`fetch-events` end to end: scripted sources over `httpx.MockTransport`, a real SQLite ledger in
a temp directory."""

from __future__ import annotations

import importlib
import io
import itertools
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest

from last_newsletter_adapter_ledger import SqliteEventRepository
from last_newsletter_cli.command_support import LEDGER_NAME, ConfigError
from last_newsletter_cli.fetch_events_command import (
    TICKETMASTER_KEY,
    FetchEventsContext,
    FetchEventsOptions,
    execute_fetch_events,
)
from last_newsletter_core.events import (
    AllDay,
    EntityRef,
    EntityRole,
    Event,
    EventId,
    EventKind,
    MatchRule,
    Mention,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

cli_main = importlib.import_module("last_newsletter_cli.main")
_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_KEY = "test-key-not-a-real-secret"
_TZ = "America/Los_Angeles"
_TM_URL = "https://www.ticketmaster.com/event/tm-1"
_ATTRIBUTION = "Event data from Frequent Flyer (https://frequentflyerla.com). Please link back."


def _tm_event(event_id: str, name: str, day: str, *, status: str = "onsale") -> dict[str, object]:
    return {
        "id": event_id,
        "name": name,
        "url": f"https://www.ticketmaster.com/event/{event_id}",
        "dates": {
            "start": {"localDate": day, "localTime": "20:00:00"},
            "timezone": _TZ,
            "status": {"code": status},
        },
        "classifications": [{"segment": {"name": "Music"}, "genre": {"name": "Rock"}}],
        "_embedded": {"venues": [{"name": "The Fonda Theatre", "city": {"name": "Los Angeles"}}]},
    }


_TM_PAGE: dict[str, object] = {
    "_embedded": {
        "events": [
            _tm_event("tm-1", "Mdou Moctar", "2026-11-20"),
            _tm_event("tm-2", "Dub Club", "2026-11-21"),
            _tm_event("tm-3", "Called Off", "2026-11-22", status="canceled"),
        ]
    },
    "page": {"size": 200, "totalElements": 3, "totalPages": 1, "number": 0},
}


def _ff_event(event_id: str, title: str, day: str, *, ticket_url: str) -> dict[str, object]:
    return {
        "id": event_id,
        "title": title,
        "date": day,
        "start_time": "20:00",
        "timezone": _TZ,
        "venue": {"name": "The Fonda Theatre"},
        "ticket_url": ticket_url,
    }


def _ff_body(events: list[dict[str, object]]) -> dict[str, object]:
    return {
        "city": "Los Angeles",
        "attribution": _ATTRIBUTION,
        "count": len(events),
        "total_matching": len(events),
        "events": events,
    }


def _ss_item(item_id: str, title: str, day: int = 20) -> dict[str, object]:
    start = int(datetime(2026, 11, day, 20, 0, tzinfo=ZoneInfo(_TZ)).timestamp() * 1000)
    return {
        "id": item_id,
        "title": title,
        "startDate": start,
        "endDate": start + 7_200_000,
        "fullUrl": f"/events/{item_id}",
        "excerpt": "<p>Doors at eight.</p>",
        "tags": [],
        "updatedOn": 1_794_000_000_000,
    }


def _ss_page(*upcoming: dict[str, object]) -> dict[str, object]:
    return {"collection": {}, "upcoming": list(upcoming), "past": []}


def _lodge_show(show_id: int, title: str) -> dict[str, object]:
    return {
        "id": show_id,
        "link": f"https://www.lodgeroomhlp.com/shows/s{show_id}/",
        "title": {"rendered": title},
        "modified_gmt": "2026-11-04T22:23:09",
        "acf": {
            "date_and_time_of_show": "11/24/2026 8:00 pm",
            "headliner": [{"post_title": title}],
            "additional_artists": [[{"post_title": "Opener"}]],
            "venue": {"post_title": "Lodge Room"},
            "ages": {"label": "ALL AGES"},
        },
    }


def _scribble_result(title: str) -> dict[str, object]:
    record = {"_id": "sc1", "title": title, "date": "2026-11-26T03:30:00.000Z"}
    return {"query": "q", "result": [record]}


@dataclass
class FakeWorld:
    """Routes requests by host, like the real two services."""

    tm_status: int = 200
    tm_body: dict[str, object] = field(default_factory=lambda: _TM_PAGE)
    ff_body: dict[str, object] = field(
        default_factory=lambda: _ff_body(
            [_ff_event("ff-1", "Zebulon Night", "2026-11-24", ticket_url="https://x.example/z")]
        )
    )
    ics: str = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\n"
        "BEGIN:VEVENT\r\nUID:ical-1@example.com\r\nSUMMARY:Zebulon Matinee\r\n"
        "DTSTART:20261125T230000Z\r\nLOCATION:Zebulon\\, 2478 Fletcher Dr\\, Los Angeles\r\n"
        "URL:https://calendar.example.com/e/1\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:ical-2@example.com\r\nSUMMARY:Mdou Moctar\r\n"
        "DTSTART:20261121T040000Z\r\nLOCATION:The Fonda Theatre\\, 6126 Hollywood Blvd\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    lodge_body: list[dict[str, object]] = field(
        default_factory=lambda: [_lodge_show(1, "Lodge Band")]
    )
    scribble_body: dict[str, object] = field(
        default_factory=lambda: _scribble_result("Scribble Night")
    )
    ics_status: int = 200
    ss_body: dict[str, object] = field(
        default_factory=lambda: _ss_page(_ss_item("s1", "Zebulon Matinee"))
    )
    hosts: list[str] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.hosts.append(host)
        routes: dict[str, Callable[[], httpx.Response]] = {
            "app.ticketmaster.com": lambda: httpx.Response(self.tm_status, json=self.tm_body),
            "frequentflyerla.com": lambda: httpx.Response(200, json=self.ff_body),
            "www.lodgeroomhlp.com": lambda: httpx.Response(
                200, json=self.lodge_body, headers={"X-WP-TotalPages": "1"}
            ),
            "59zw0zbs.apicdn.sanity.io": lambda: httpx.Response(200, json=self.scribble_body),
            "www.venue.example": lambda: httpx.Response(200, json=self.ss_body),
            "calendar.example.com": lambda: httpx.Response(
                self.ics_status, text=self.ics, headers={"content-type": "text/calendar"}
            ),
        }
        return routes.get(host, lambda: httpx.Response(404))()

    @property
    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


_NEXT_ID = itertools.count(1)


class _Ids:
    """Ids unique across runs in one test, like the random UUIDs production uses."""

    def new_event_id(self) -> EventId:
        return EventId(UUID(int=next(_NEXT_ID)))


@dataclass
class Run:
    code: int
    out: str
    err: str


def _run(
    data_dir: Path,
    world: FakeWorld,
    *,
    source: str = "ticketmaster",
    dry_run: bool = False,
    days: int = 60,
    key: str | None = _KEY,
    city: str = "Los Angeles",
    feed_url: str = "",
    feed_name: str = "",
    feed_venue: str = "",
    feed_organizer: str = "",
) -> Run:
    out, err = io.StringIO(), io.StringIO()
    environ = {TICKETMASTER_KEY: key} if key is not None else {}
    code = execute_fetch_events(
        FetchEventsContext(
            data_dir=data_dir,
            now=_NOW,
            environ=environ,
            out=out,
            err=err,
            ids=_Ids(),
            http=world.client,
            sleep=lambda _s: None,
        ),
        FetchEventsOptions(
            source=source,
            city=city,
            region="CA",
            days=days,
            home_tz=_TZ,
            dry_run=dry_run,
            feed_url=feed_url,
            feed_name=feed_name,
            feed_venue=feed_venue,
            feed_organizer=feed_organizer,
        ),
    )
    return Run(code, out.getvalue(), err.getvalue())


def _stored(data_dir: Path) -> list[Event]:
    with SqliteEventRepository(data_dir / "events" / LEDGER_NAME) as ledger:
        return ledger.list_all()


# --- ticketmaster ------------------------------------------------------------------------------


def test_a_real_run_stores_the_events_with_the_source_as_provenance(tmp_path: Path) -> None:
    result = _run(tmp_path, FakeWorld())
    assert result.code == 0
    assert "events: 2 created, 0 new mentions, 0 unchanged" in result.out
    assert "skipped: cancelled 1" in result.out
    stored = {e.title: e for e in _stored(tmp_path)}
    assert set(stored) == {"Mdou Moctar", "Dub Club"}
    assert [m.source for m in stored["Mdou Moctar"].mentions] == ["ticketmaster"]
    assert stored["Mdou Moctar"].uid == "ticketmaster:tm-1"


def test_a_second_run_changes_nothing(tmp_path: Path) -> None:
    _run(tmp_path, FakeWorld())
    again = _run(tmp_path, FakeWorld())
    assert "events: 0 created, 0 new mentions, 2 unchanged" in again.out
    assert len(_stored(tmp_path)) == 2


def test_a_dry_run_reports_the_same_counts_and_saves_nothing(tmp_path: Path) -> None:
    result = _run(tmp_path, FakeWorld(), dry_run=True)
    assert result.code == 0
    assert "DRY RUN: nothing below was saved" in result.out
    assert "events: 2 created" in result.out
    assert not (tmp_path / "events" / LEDGER_NAME).exists()


def test_a_dry_run_does_not_touch_an_existing_ledger(tmp_path: Path) -> None:
    _run(tmp_path, FakeWorld())
    before = sorted(p.name for p in (tmp_path / "events").iterdir())
    again = _run(tmp_path, FakeWorld(), dry_run=True)
    assert "2 unchanged" in again.out
    assert sorted(p.name for p in (tmp_path / "events").iterdir()) == before
    assert len(_stored(tmp_path)) == 2


def test_an_event_already_known_from_a_newsletter_is_cited_not_duplicated(tmp_path: Path) -> None:
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    seen = datetime(2026, 11, 1, tzinfo=UTC)
    known = EventId(UUID(int=500))
    with SqliteEventRepository(events_dir / LEDGER_NAME) as ledger:
        ledger.upsert(
            Event(
                id=known,
                kind=EventKind.EVENT,
                title="Mdou Moctar",
                summary="",
                when=AllDay(date(2026, 11, 20)),
                entities=(EntityRef(name="The Fonda Theatre", role=EntityRole.VENUE),),
                mentions=(
                    Mention(
                        message_id="mail-1",
                        seen_at=seen,
                        source="venue newsletter",
                        evidence="Fri Nov 20 Mdou Moctar",
                        match_rule=MatchRule.NEW,
                        cited_event_id=known,
                    ),
                ),
                first_seen=seen,
                last_seen=seen,
            )
        )
    result = _run(tmp_path, FakeWorld())
    assert "events: 1 created, 1 new mentions" in result.out
    stored = {e.title: e for e in _stored(tmp_path)}
    assert set(stored) == {"Mdou Moctar", "Dub Club"}
    assert [m.source for m in stored["Mdou Moctar"].mentions] == [
        "venue newsletter",
        "ticketmaster",
    ]


def test_the_output_is_counts_only(tmp_path: Path) -> None:
    result = _run(tmp_path, FakeWorld())
    shown = result.out + result.err
    for secret in (_KEY, "Mdou Moctar", "Dub Club", "Fonda", "tm-1"):
        assert secret not in shown


def test_a_rejected_key_fails_cleanly_and_saves_nothing(tmp_path: Path) -> None:
    result = _run(tmp_path, FakeWorld(tm_status=401))
    assert result.code == 1
    assert "rejected the API key" in result.err
    assert "nothing was saved" in result.err
    assert _KEY not in result.out + result.err
    assert not (tmp_path / "events" / LEDGER_NAME).exists()


def test_a_missing_key_is_a_configuration_error_before_any_request(tmp_path: Path) -> None:
    world = FakeWorld()
    with pytest.raises(ConfigError, match=TICKETMASTER_KEY):
        _run(tmp_path, world, key=None)
    assert world.hosts == []


@pytest.mark.parametrize(("days", "city"), [(0, "Los Angeles"), (366, "Los Angeles"), (30, "  ")])
def test_bad_options_are_configuration_errors(tmp_path: Path, days: int, city: str) -> None:
    world = FakeWorld()
    with pytest.raises(ConfigError):
        _run(tmp_path, world, days=days, city=city)
    assert world.hosts == []


# --- frequent flyer ----------------------------------------------------------------------------


def test_frequent_flyer_needs_no_key_and_no_city(tmp_path: Path) -> None:
    world = FakeWorld()
    result = _run(tmp_path, world, source="frequentflyer", key=None, city="")
    assert result.code == 0
    assert "events: 1 created" in result.out
    assert set(world.hosts) == {"frequentflyerla.com"}
    (event,) = _stored(tmp_path)
    assert event.uid == "frequentflyer:ff-1"
    assert [m.source for m in event.mentions] == ["frequentflyer"]


def test_the_attribution_the_source_requires_is_printed(tmp_path: Path) -> None:
    result = _run(tmp_path, FakeWorld(), source="frequentflyer", key=None)
    assert f"note: {_ATTRIBUTION}" in result.out


def test_a_frequent_flyer_rerun_changes_nothing(tmp_path: Path) -> None:
    _run(tmp_path, FakeWorld(), source="frequentflyer")
    again = _run(tmp_path, FakeWorld(), source="frequentflyer")
    assert "events: 0 created, 0 new mentions, 1 unchanged" in again.out


def test_the_same_show_from_two_sources_is_one_event_with_two_mentions(tmp_path: Path) -> None:
    _run(tmp_path, FakeWorld())
    world = FakeWorld(
        ff_body=_ff_body(
            [_ff_event("ff-9", "Mdou Moctar (live)", "2026-11-20", ticket_url=_TM_URL)]
        )
    )
    result = _run(tmp_path, world, source="frequentflyer")
    assert "events: 0 created, 1 new mentions" in result.out
    stored = {e.title: e for e in _stored(tmp_path)}
    assert len(stored) == 2
    assert [m.source for m in stored["Mdou Moctar"].mentions] == ["ticketmaster", "frequentflyer"]
    assert stored["Mdou Moctar"].mentions[-1].match_rule is MatchRule.URL


def test_an_unknown_source_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown source"):
        _run(tmp_path, FakeWorld(), source="songkick")


# --- ical --------------------------------------------------------------------------------------

_FEED = "https://calendar.example.com/feed.ics?token=SECRET-TOKEN"


def test_an_ical_feed_needs_no_key_and_is_labelled_by_its_name(tmp_path: Path) -> None:
    world = FakeWorld()
    result = _run(tmp_path, world, source="ical", key=None, feed_url=_FEED, feed_name="mycal")
    assert result.code == 0
    assert "events: 2 created" in result.out
    assert set(world.hosts) == {"calendar.example.com"}
    stored = {e.title: e for e in _stored(tmp_path)}
    assert set(stored) == {"Zebulon Matinee", "Mdou Moctar"}
    zebulon = stored["Zebulon Matinee"]
    assert zebulon.uid == "ical-1@example.com"
    assert zebulon.venue == "Zebulon"
    assert [m.source for m in zebulon.mentions] == ["mycal"]


def test_the_feed_host_names_the_source_when_no_name_is_given(tmp_path: Path) -> None:
    _run(tmp_path, FakeWorld(), source="ical", key=None, feed_url=_FEED)
    sources = {m.source for e in _stored(tmp_path) for m in e.mentions}
    assert sources == {"calendar.example.com"}


def test_an_ical_rerun_changes_nothing_and_the_token_is_never_printed(tmp_path: Path) -> None:
    _run(tmp_path, FakeWorld(), source="ical", key=None, feed_url=_FEED)
    again = _run(tmp_path, FakeWorld(), source="ical", key=None, feed_url=_FEED)
    assert "events: 0 created, 0 new mentions, 2 unchanged" in again.out
    assert "SECRET-TOKEN" not in again.out + again.err


def test_a_calendar_event_matching_a_ticketmaster_event_is_cited_not_duplicated(
    tmp_path: Path,
) -> None:
    _run(tmp_path, FakeWorld())
    result = _run(tmp_path, FakeWorld(), source="ical", key=None, feed_url=_FEED, feed_name="mycal")
    assert "events: 1 created, 1 new mentions" in result.out
    stored = {e.title: e for e in _stored(tmp_path)}
    assert [m.source for m in stored["Mdou Moctar"].mentions] == ["ticketmaster", "mycal"]
    assert stored["Mdou Moctar"].mentions[-1].match_rule is MatchRule.TITLE_DATE_VENUE


@pytest.mark.parametrize("url", ["", "calendar.example.com/feed.ics", "file:///etc/passwd"])
def test_an_ical_source_needs_a_web_url(tmp_path: Path, url: str) -> None:
    world = FakeWorld()
    with pytest.raises(ConfigError, match="--feed-url"):
        _run(tmp_path, world, source="ical", key=None, feed_url=url)
    assert world.hosts == []


def test_a_broken_feed_url_fails_cleanly_without_the_token(tmp_path: Path) -> None:
    result = _run(tmp_path, FakeWorld(ics_status=404), source="ical", key=None, feed_url=_FEED)
    assert result.code == 1
    assert "HTTP 404" in result.err
    assert "SECRET-TOKEN" not in result.out + result.err
    assert not (tmp_path / "events" / LEDGER_NAME).exists()


# --- squarespace -------------------------------------------------------------------------------

_PAGE = "https://www.venue.example/events"


def test_a_squarespace_events_page_needs_no_key_and_is_labelled_by_its_name(tmp_path: Path) -> None:
    world = FakeWorld()
    result = _run(
        tmp_path,
        world,
        source="squarespace",
        key=None,
        feed_url=_PAGE,
        feed_name="room",
        feed_venue="Zebulon",
    )
    assert result.code == 0
    assert "events: 1 created" in result.out
    assert set(world.hosts) == {"www.venue.example"}
    (event,) = _stored(tmp_path)
    assert (event.title, event.venue, event.uid) == ("Zebulon Matinee", "Zebulon", "room:s1")
    assert [m.source for m in event.mentions] == ["room"]


def test_a_promoters_feed_records_an_organizer_and_no_venue(tmp_path: Path) -> None:
    _run(
        tmp_path,
        FakeWorld(),
        source="squarespace",
        key=None,
        feed_url=_PAGE,
        feed_organizer="Living Earth",
    )
    (event,) = _stored(tmp_path)
    assert event.venue == ""
    assert [(e.name, e.role) for e in event.entities] == [("Living Earth", EntityRole.ORGANIZER)]


def test_a_squarespace_rerun_changes_nothing(tmp_path: Path) -> None:
    for _ in range(2):
        again = _run(
            tmp_path,
            FakeWorld(),
            source="squarespace",
            key=None,
            feed_url=_PAGE,
            feed_venue="Zebulon",
        )
    assert "events: 0 created, 0 new mentions, 1 unchanged" in again.out


def test_a_squarespace_show_matching_a_ticketmaster_event_is_cited(tmp_path: Path) -> None:
    _run(tmp_path, FakeWorld())
    world = FakeWorld(ss_body=_ss_page(_ss_item("s9", "Mdou Moctar")))
    result = _run(
        tmp_path,
        world,
        source="squarespace",
        key=None,
        feed_url=_PAGE,
        feed_name="fonda",
        feed_venue="The Fonda Theatre",
    )
    assert "events: 0 created, 1 new mentions" in result.out
    stored = {e.title: e for e in _stored(tmp_path)}
    assert [m.source for m in stored["Mdou Moctar"].mentions] == ["ticketmaster", "fonda"]


@pytest.mark.parametrize(("venue", "organizer"), [("", ""), ("A room", "A promoter")])
def test_a_squarespace_feed_must_say_exactly_one_of_venue_or_organizer(
    tmp_path: Path, venue: str, organizer: str
) -> None:
    world = FakeWorld()
    with pytest.raises(ConfigError, match="exactly one of"):
        _run(
            tmp_path,
            world,
            source="squarespace",
            key=None,
            feed_url=_PAGE,
            feed_venue=venue,
            feed_organizer=organizer,
        )
    assert world.hosts == []


def test_an_organizer_makes_no_sense_for_an_ical_feed(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not used by the ical source"):
        _run(tmp_path, FakeWorld(), source="ical", key=None, feed_url=_FEED, feed_organizer="X")


# --- single venues -----------------------------------------------------------------------------


def test_lodge_room_needs_no_flags_and_records_headliner_support_and_venue(tmp_path: Path) -> None:
    world = FakeWorld()
    result = _run(tmp_path, world, source="lodgeroom", key=None, city="")
    assert result.code == 0
    assert "events: 1 created" in result.out
    assert set(world.hosts) == {"www.lodgeroomhlp.com"}
    (event,) = _stored(tmp_path)
    assert (event.title, event.uid, event.venue) == ("Lodge Band", "lodgeroom:1", "Lodge Room")
    roles = {(e.name, e.role) for e in event.entities}
    assert ("Lodge Band", EntityRole.HEADLINER) in roles
    assert ("Opener", EntityRole.SUPPORT) in roles
    assert [m.source for m in event.mentions] == ["lodgeroom"]


def test_scribble_is_shown_in_the_home_zone_and_a_rerun_changes_nothing(tmp_path: Path) -> None:
    first = _run(tmp_path, FakeWorld(), source="scribble", key=None, city="")
    assert "events: 1 created" in first.out
    (event,) = _stored(tmp_path)
    assert event.venue == "Scribble"
    assert event.uid == "scribble:sc1"
    again = _run(tmp_path, FakeWorld(), source="scribble", key=None, city="")
    assert "events: 0 created, 0 new mentions, 1 unchanged" in again.out


# --- wiring ------------------------------------------------------------------------------------


def test_the_command_is_wired_into_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli_main, "_DATA_DIR", tmp_path)
    monkeypatch.delenv(TICKETMASTER_KEY, raising=False)
    with pytest.raises(SystemExit) as stop:
        cli_main.main(["fetch-events", "--city", "Los Angeles"])
    assert stop.value.code == 2
    assert TICKETMASTER_KEY in capsys.readouterr().err
