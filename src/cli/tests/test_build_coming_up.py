"""`build` and the Coming up section: a synthetic ledger, no real mail, a fixed clock.

The ledger is only ever opened read-only; a missing, locked, corrupt or out-of-date ledger costs
the digest its section (one warning) and nothing else.
"""

from __future__ import annotations

import importlib
import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from test_local_pipeline_e2e import _SINCE, FakeOllama, _Mailbox, _process

from last_newsletter_adapter_ledger import MIGRATIONS, SqliteEventRepository, migrate
from last_newsletter_adapter_publish.render import render_html
from last_newsletter_adapter_storage import FileRawMessageStore
from last_newsletter_cli.main import fetch_raw
from last_newsletter_core.entities import Cadence, Digest, EmailMessage
from last_newsletter_core.events import (
    AllDay,
    EntityRef,
    EntityRole,
    Event,
    EventId,
    EventKind,
    ItemState,
    MatchRule,
    Mention,
    Timed,
)

if TYPE_CHECKING:
    from pathlib import Path

cli_main = importlib.import_module("last_newsletter_cli.main")
upcoming_section = importlib.import_module("last_newsletter_cli.upcoming_section")

_NOW = datetime(2026, 11, 7, 12, tzinfo=UTC)  # 04:00 in Los Angeles
_LA = "America/Los_Angeles"
_SEEN = datetime(2026, 11, 1, tzinfo=UTC)


def _id(n: int) -> EventId:
    return EventId(UUID(int=n))


def _event(n: int, when: Timed | AllDay, title: str, mentions: int = 1, **extra: object) -> Event:
    cites = tuple(
        Mention(
            message_id=f"<m{n}-{k}@fixture.test>",
            seen_at=_SEEN,
            source="s",
            evidence=f"quote {k}",
            match_rule=MatchRule.NEW if k == 0 else MatchRule.UID,
            cited_event_id=_id(n),
        )
        for k in range(mentions)
    )
    base = Event(
        id=_id(n),
        kind=EventKind.EVENT,
        title=title,
        summary="",
        when=when,
        mentions=cites,
        first_seen=_SEEN,
        last_seen=_SEEN,
    )
    return replace(base, **extra)


def _la(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=ZoneInfo(_LA))


def _timed(start: datetime, end: datetime | None = None) -> Timed:
    return Timed(start=start, tz_name=_LA, end=end)


def synthetic_events() -> list[Event]:
    return [
        _event(
            1,
            _timed(_la(11, 13, 22), _la(11, 14, 2)),
            "Overnight Party",
            entities=(EntityRef("The Warehouse", EntityRole.VENUE),),
            city="Portland",
        ),
        _event(
            2,
            _timed(_la(11, 14, 12)),
            "Film Matinee",
            showtimes=(time(12), time(15, 30), time(19)),
            url="https://example.test/film",
        ),
        _event(3, AllDay(date(2026, 11, 14)), "Street Market", mentions=3),
        _event(4, _timed(_la(11, 5, 20)), "Already Happened"),
        _event(5, _timed(_la(11, 14, 20)), "Finished Task", state=ItemState.DONE),
        _event(6, _timed(_la(11, 14, 21)), "Dismissed Show", state=ItemState.DISMISSED),
        _event(7, _timed(_la(12, 30, 20)), "Far Future"),
        _event(8, _timed(_la(11, 7, 9)), "Later Today"),
    ]


def make_ledger(data_dir: Path, events: list[Event] | None = None) -> Path:
    path = data_dir / "events" / "ledger.sqlite"
    with SqliteEventRepository(path) as repo:
        for event in synthetic_events() if events is None else events:
            repo.upsert(event)
    return path


def _raw_mail(data_dir: Path) -> None:
    store = FileRawMessageStore(data_dir / "raw")
    store.put(
        EmailMessage(
            message_id="<only@fixture.test>",
            sender="a@fixture.test",
            subject="Hello",
            received_at=datetime(2026, 11, 3, 9, tzinfo=UTC),
            body_text="Nothing dated here.",
            source_label="a@fixture.test",
        )
    )


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cli_main, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(cli_main, "_now", lambda: _NOW)
    _raw_mail(tmp_path)
    return tmp_path


def _build(data_dir: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[str, str, str]:
    capsys.readouterr()
    cli_main.main(["build", "--home-tz", _LA, *args])
    captured = capsys.readouterr()
    [path] = sorted((data_dir / "markdown").glob("*.md"))
    return captured.out, captured.err, path.read_text()


def test_build_lists_upcoming_events_by_date_and_prints_one_count_line(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_ledger(data_dir)
    out, err, md = _build(data_dir, capsys)
    assert err == ""
    assert "coming up: 4 upcoming event(s) on 3 date(s), 2026-11-07 to 2026-11-14" in out
    assert out.count("coming up:") == 1
    assert "## Coming up: Sat Nov 7 to Fri Nov 20" in md
    assert md.index("### Sat Nov 7") < md.index("### Fri Nov 13") < md.index("### Sat Nov 14")
    for title in ("Overnight Party", "Film Matinee", "Street Market", "Later Today"):
        assert title in md
    for title in ("Already Happened", "Finished Task", "Dismissed Show", "Far Future"):
        assert title not in md


def test_overnight_showtimes_and_citations_read_correctly(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_ledger(data_dir)
    _, _, md = _build(data_dir, capsys)
    assert "10:00 PM \N{EN DASH} 2:00 AM Sat Nov 14" in md
    assert "The Warehouse, Portland" in md
    assert "12:00 PM, 3:30 PM, 7:00 PM" in md
    assert "(in 3 emails)" in md
    assert "[link](<https://example.test/film>)" in md
    saturday = md[md.index("### Sat Nov 14") :]
    assert saturday.index("Street Market") < saturday.index("Film Matinee")  # all-day first


def test_event_uuids_stay_out_of_the_human_text(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_ledger(data_dir)
    _, _, md = _build(data_dir, capsys)
    assert f"<!-- event:{_id(1)} -->" in md
    visible = "\n".join(line.split("<!--")[0] for line in md.splitlines())
    assert str(_id(1)) not in visible


def test_event_days_narrows_the_window(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_ledger(data_dir)
    out, _, md = _build(data_dir, capsys, "--event-days", "1")
    assert "coming up: 1 upcoming event(s) on 1 date(s)" in out
    assert "Later Today" in md
    assert "Street Market" not in md


def test_event_days_wider_reaches_far_events(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_ledger(data_dir)
    out, _, md = _build(data_dir, capsys, "--event-days", "60")
    assert "5 upcoming event(s) on 4 date(s)" in out
    assert "Far Future" in md


@pytest.mark.parametrize("days", ["0", "-3", "9999"])
def test_bad_event_days_is_a_usage_error(
    data_dir: Path, capsys: pytest.CaptureFixture[str], days: str
) -> None:
    make_ledger(data_dir)
    with pytest.raises(SystemExit) as stop:
        cli_main.main(["build", "--event-days", days])
    assert stop.value.code == 2
    assert "--event-days" in capsys.readouterr().err


@pytest.mark.usefixtures("data_dir")
def test_bad_home_tz_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        cli_main.main(["build", "--home-tz", "Nowhere/City"])
    assert stop.value.code == 2
    assert "time zone" in capsys.readouterr().err


def test_no_events_flag_skips_the_ledger_entirely(
    data_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    make_ledger(data_dir)

    def boom(*_a: object, **_k: object) -> None:
        pytest.fail("the ledger must not be opened with --no-events")

    monkeypatch.setattr(upcoming_section, "SqliteEventRepository", boom)
    out, err, md = _build(data_dir, capsys, "--no-events")
    assert "coming up: skipped (--no-events)" in out
    assert err == ""
    assert "Coming up" not in md


def test_empty_ledger_omits_the_section(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_ledger(data_dir, [])
    out, err, md = _build(data_dir, capsys)
    assert "coming up: 0 upcoming events in the next 14 day(s); section omitted" in out
    assert err == ""
    assert "Coming up" not in md


def test_ledger_with_only_past_and_closed_events_omits_the_section(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    only_closed = [e for e in synthetic_events() if e.id in {_id(4), _id(5), _id(6)}]
    make_ledger(data_dir, only_closed)
    out, _, md = _build(data_dir, capsys)
    assert "0 upcoming events" in out
    assert "Coming up" not in md


def test_missing_ledger_builds_quietly_and_creates_nothing(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out, err, md = _build(data_dir, capsys)
    assert "coming up: no event ledger yet" in out
    assert err == ""
    assert "Coming up" not in md
    assert not (data_dir / "events").exists()


def test_locked_ledger_warns_once_and_still_builds(
    data_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    make_ledger(data_dir)

    def locked(*_a: object, **_k: object) -> None:
        msg = "database is locked"
        raise sqlite3.OperationalError(msg)

    monkeypatch.setattr(upcoming_section, "SqliteEventRepository", locked)
    out, err, md = _build(data_dir, capsys)
    assert err.count("warning:") == 1
    assert "locked" in err
    assert "coming up: skipped (ledger unreadable)" in out
    assert "Weekly digest" in md
    assert "Coming up" not in md


def test_a_writer_mid_transaction_does_not_block_the_digest(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = make_ledger(data_dir)
    writer = sqlite3.connect(path, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    try:
        out, err, md = _build(data_dir, capsys)
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    assert err == ""
    assert "4 upcoming event(s)" in out
    assert "Street Market" in md


def test_old_schema_warns_once_leaves_the_file_alone_and_still_builds(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = data_dir / "events" / "ledger.sqlite"
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(path, isolation_level=None)
    migrate(conn, MIGRATIONS[:1])
    conn.close()
    before = path.read_bytes()
    out, err, md = _build(data_dir, capsys)
    assert err.count("warning:") == 1
    assert "`process`" in err
    assert "skipped" in out
    assert "Weekly digest" in md
    assert path.read_bytes() == before


def test_corrupt_ledger_warns_and_still_builds(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = data_dir / "events" / "ledger.sqlite"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"this is not a database" * 50)
    out, err, md = _build(data_dir, capsys)
    assert err.count("warning:") == 1
    assert "skipped" in out
    assert "Weekly digest" in md


def test_the_real_ledger_is_not_modified_by_a_build(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = make_ledger(data_dir)
    files = {p.name: p.read_bytes() for p in path.parent.iterdir() if p.suffix == ".sqlite"}
    _build(data_dir, capsys)
    assert {p.name: p.read_bytes() for p in path.parent.iterdir() if p.suffix == ".sqlite"} == files


def test_hostile_text_in_the_ledger_cannot_inject_markup(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nasty = '<script>alert(1)</script> *x* [y](http://evil.test) & "q"'
    make_ledger(data_dir, [_event(1, _timed(_la(11, 13, 20)), nasty, city="<b>c</b>")])
    _, _, md = _build(data_dir, capsys)
    assert "<script>" not in md
    assert "<b>c</b>" not in md
    assert r"\<script\>" in md


def test_very_long_title_is_shortened_in_the_digest(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_ledger(data_dir, [_event(1, _timed(_la(11, 13, 20)), "T" * 4000)])
    _, _, md = _build(data_dir, capsys)
    assert "T" * 200 not in md
    assert "\N{HORIZONTAL ELLIPSIS}" in md


def test_dst_fall_back_day_in_los_angeles(
    data_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 2026-11-01 is the day clocks go back; 08:00 UTC is 01:00 PDT, before the repeated hour.
    monkeypatch.setattr(cli_main, "_now", lambda: datetime(2026, 11, 1, 8, 0, tzinfo=UTC))
    edge = [
        _event(1, _timed(_la(11, 1, 1, 30)), "Twice Hour", showtimes=(time(1, 30), time(20))),
        _event(2, AllDay(date(2026, 11, 14)), "Last Day In Window"),
        _event(3, AllDay(date(2026, 11, 15)), "Just Outside"),
    ]
    make_ledger(data_dir, edge)
    out, _, md = _build(data_dir, capsys)
    assert "2 upcoming event(s)" in out
    assert "Twice Hour" in md
    assert "Last Day In Window" in md
    assert "Just Outside" not in md


def test_html_digest_via_the_publisher_stays_themed_and_has_the_data_attribute(
    data_dir: Path,
) -> None:
    outcome = upcoming_section.load_upcoming(make_ledger(data_dir), now=_NOW, days=14, tz_name=_LA)
    digest = Digest(_NOW, _NOW, Cadence.WEEKLY, (), 0, 0)
    html = render_html(digest, outcome.upcoming)
    assert f'data-event-id="{_id(1)}"' in html
    assert "Street Market" in html


def test_end_to_end_raw_mail_to_process_to_build_has_a_coming_up_section(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fetch_raw(_Mailbox(), FileRawMessageStore(data_dir / "raw"), since=_SINCE)
    code, _, err = _process(data_dir, FakeOllama())
    assert (code, err) == (0, "")

    out, err, md = _build(data_dir, capsys, "--event-days", "60")
    assert err == ""
    assert "coming up: 3 upcoming event(s) on 2 date(s), 2026-12-12 to 2026-12-20" in out
    assert "## Coming up" in md
    assert md.index("## Coming up") < md.index("## ", md.index("## Coming up") + 5)
    assert "### Sat Dec 12" in md
    assert "### Sun Dec 20" in md
    assert "Quiz Night" in md
    assert "Moon Party" in md
    assert "(in 2 emails)" in md  # the repeated mention is cited on the one event
    assert "<!-- event:" in md
