"""`fetch-events` end to end: a scripted Ticketmaster, a real SQLite ledger in a temp directory."""

from __future__ import annotations

import importlib
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from http_transport import HttpResponse
from last_newsletter_adapter_ledger import SqliteEventRepository
from last_newsletter_cli.fetch_events_command import (
    KEY_VARIABLE,
    FetchEventsContext,
    FetchEventsOptions,
    execute_fetch_events,
)
from last_newsletter_cli.process_command import LEDGER_NAME, ConfigError
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


def _event(event_id: str, name: str, day: str, *, status: str = "onsale") -> dict[str, object]:
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


_PAGE: dict[str, object] = {
    "_embedded": {
        "events": [
            _event("tm-1", "Mdou Moctar", "2026-11-20"),
            _event("tm-2", "Dub Club", "2026-11-21"),
            _event("tm-3", "Called Off", "2026-11-22", status="canceled"),
        ]
    },
    "page": {"size": 200, "totalElements": 3, "totalPages": 1, "number": 0},
}


@dataclass
class FakeTicketmaster:
    status: int = 200
    body: dict[str, object] = field(default_factory=lambda: _PAGE)
    urls: list[str] = field(default_factory=list)

    def get(self, url: str, *, timeout_s: float) -> HttpResponse:
        _ = timeout_s
        self.urls.append(url)
        return HttpResponse(self.status, json.dumps(self.body).encode())


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
    transport: FakeTicketmaster,
    *,
    dry_run: bool = False,
    days: int = 60,
    key: str | None = _KEY,
    city: str = "Los Angeles",
) -> Run:
    out, err = io.StringIO(), io.StringIO()
    environ = {KEY_VARIABLE: key} if key is not None else {}
    code = execute_fetch_events(
        FetchEventsContext(
            data_dir=data_dir,
            now=_NOW,
            environ=environ,
            out=out,
            err=err,
            ids=_Ids(),
            transport=transport,
            sleep=lambda _s: None,
        ),
        FetchEventsOptions(city=city, region="CA", days=days, home_tz=_TZ, dry_run=dry_run),
    )
    return Run(code, out.getvalue(), err.getvalue())


def _stored(data_dir: Path) -> list[Event]:
    with SqliteEventRepository(data_dir / "events" / LEDGER_NAME) as ledger:
        return ledger.list_all()


def test_a_real_run_stores_the_events_with_the_source_as_provenance(tmp_path: Path) -> None:
    result = _run(tmp_path, FakeTicketmaster())
    assert result.code == 0
    assert "events: 2 created, 0 new mentions, 0 unchanged" in result.out
    assert "skipped: cancelled 1" in result.out
    stored = {e.title: e for e in _stored(tmp_path)}
    assert set(stored) == {"Mdou Moctar", "Dub Club"}
    assert [m.source for m in stored["Mdou Moctar"].mentions] == ["ticketmaster"]
    assert stored["Mdou Moctar"].uid == "ticketmaster:tm-1"


def test_a_second_run_changes_nothing(tmp_path: Path) -> None:
    _run(tmp_path, FakeTicketmaster())
    again = _run(tmp_path, FakeTicketmaster())
    assert "events: 0 created, 0 new mentions, 2 unchanged" in again.out
    assert len(_stored(tmp_path)) == 2


def test_a_dry_run_reports_the_same_counts_and_saves_nothing(tmp_path: Path) -> None:
    result = _run(tmp_path, FakeTicketmaster(), dry_run=True)
    assert result.code == 0
    assert "DRY RUN: nothing below was saved" in result.out
    assert "events: 2 created" in result.out
    assert not (tmp_path / "events" / LEDGER_NAME).exists()


def test_a_dry_run_does_not_touch_an_existing_ledger(tmp_path: Path) -> None:
    _run(tmp_path, FakeTicketmaster())
    before = sorted(p.name for p in (tmp_path / "events").iterdir())
    again = _run(tmp_path, FakeTicketmaster(), dry_run=True)
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
    result = _run(tmp_path, FakeTicketmaster())
    assert "events: 1 created, 1 new mentions" in result.out
    stored = {e.title: e for e in _stored(tmp_path)}
    assert set(stored) == {"Mdou Moctar", "Dub Club"}
    assert [m.source for m in stored["Mdou Moctar"].mentions] == [
        "venue newsletter",
        "ticketmaster",
    ]


def test_the_output_is_counts_only(tmp_path: Path) -> None:
    result = _run(tmp_path, FakeTicketmaster())
    shown = result.out + result.err
    for secret in (_KEY, "Mdou Moctar", "Dub Club", "Fonda", "tm-1"):
        assert secret not in shown


def test_a_rejected_key_fails_cleanly_and_saves_nothing(tmp_path: Path) -> None:
    result = _run(tmp_path, FakeTicketmaster(status=401))
    assert result.code == 1
    assert "rejected the API key" in result.err
    assert "nothing was saved" in result.err
    assert _KEY not in result.out + result.err
    assert not (tmp_path / "events" / LEDGER_NAME).exists()


def test_a_missing_key_is_a_configuration_error_before_any_request(tmp_path: Path) -> None:
    transport = FakeTicketmaster()
    with pytest.raises(ConfigError, match=KEY_VARIABLE):
        _run(tmp_path, transport, key=None)
    assert transport.urls == []


@pytest.mark.parametrize(("days", "city"), [(0, "Los Angeles"), (366, "Los Angeles"), (30, "  ")])
def test_bad_options_are_configuration_errors(tmp_path: Path, days: int, city: str) -> None:
    transport = FakeTicketmaster()
    with pytest.raises(ConfigError):
        _run(tmp_path, transport, days=days, city=city)
    assert transport.urls == []


def test_the_command_is_wired_into_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli_main, "_DATA_DIR", tmp_path)
    monkeypatch.delenv(KEY_VARIABLE, raising=False)
    with pytest.raises(SystemExit) as stop:
        cli_main.main(["fetch-events", "--city", "Los Angeles"])
    assert stop.value.code == 2
    assert KEY_VARIABLE in capsys.readouterr().err
