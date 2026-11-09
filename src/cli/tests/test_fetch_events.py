"""`fetch-events` end to end: scripted sources over `httpx.MockTransport`, a real SQLite ledger in
a temp directory."""

from __future__ import annotations

import importlib
import io
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

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
    hosts: list[str] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.hosts.append(request.url.host)
        if request.url.host == "app.ticketmaster.com":
            return httpx.Response(self.tm_status, json=self.tm_body)
        if request.url.host == "frequentflyerla.com":
            return httpx.Response(200, json=self.ff_body)
        return httpx.Response(404)

    @property
    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


class _Ids:
    def __init__(self) -> None:
        self._n = 0

    def new_event_id(self) -> EventId:
        self._n += 1
        return EventId(UUID(int=self._n))


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
            source=source, city=city, region="CA", days=days, home_tz=_TZ, dry_run=dry_run
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
