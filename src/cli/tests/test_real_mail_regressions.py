"""Defects the first run on a real mailbox exposed, replayed with synthetic listing lines in
the generic formats the owner saw. Fake model, fixed clock, no network."""

from __future__ import annotations

import importlib
import io
import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from last_newsletter_adapter_storage import FileRawMessageStore
from last_newsletter_cli.main import fetch_raw
from last_newsletter_cli.process_command import ProcessContext, ProcessOptions, execute_process
from last_newsletter_core.entities import EmailMessage

if TYPE_CHECKING:
    from pathlib import Path

cli_main = importlib.import_module("last_newsletter_cli.main")

_NOW = datetime(2026, 11, 7, 12, tzinfo=UTC)
_ENV = {"LAST_NEWSLETTER_OLLAMA_MODEL": "fake-model"}
_RUN_A = "Sunday, November 15th - 10AM Monday, November 16th - 12:30PM, 4PM"
_RUN_B = "Tuesday, November 17th - 12:30PM, 4PM Wednesday, November 18th - 12:15PM, 3:45PM, 7:15PM"
_MON_ONLY = "Monday, November 16th - 12:30PM, 4PM"


def _mail(n: int, subject: str, body: str) -> EmailMessage:
    return EmailMessage(
        message_id=f"<m{n}@fixture.test>",
        sender="sender@fixture.test",
        subject=subject,
        received_at=datetime(2026, 11, n, 9, tzinfo=UTC),
        body_text=body,
        source_label="sender@fixture.test",
    )


class _Model:
    """subject marker -> raw events the fake model answers with."""

    def __init__(self, answers: dict[str, list[dict[str, Any]]]) -> None:
        self.answers = answers

    def post(self, url: str, body: bytes, *, timeout_s: float) -> tuple[int, bytes]:
        prompt = json.loads(body)["messages"][1]["content"]
        events = next((a for key, a in self.answers.items() if key in prompt), [])
        content = json.dumps({"events": events})
        return 200, json.dumps({"message": {"role": "assistant", "content": content}}).encode()


def _raw(title: str, start: str, *, venue: str = "The Cinema") -> dict[str, Any]:
    return {
        "title": title,
        "kind": "event",
        "start_text": start,
        "end_text": "",
        "venue": venue,
        "cancelled": False,
        "confidence": "high",
        "evidence": start,
    }


class _Source:
    def __init__(self, mails: list[EmailMessage]) -> None:
        self.mails = mails

    def fetch_since(self, since: datetime) -> list[EmailMessage]:
        return [m for m in self.mails if m.received_at >= since]


def _run(
    data_dir: Path,
    mails: list[EmailMessage],
    answers: dict[str, list[dict[str, Any]]],
    *,
    dry_run: bool = False,
    reprocess: bool = False,
) -> str:
    fetch_raw(
        _Source(mails),
        FileRawMessageStore(data_dir / "raw"),
        since=datetime(2026, 11, 1, tzinfo=UTC),
    )
    out, err = io.StringIO(), io.StringIO()
    code = execute_process(
        ProcessContext(
            data_dir=data_dir,
            now=_NOW,
            environ=_ENV,
            out=out,
            err=err,
            transport=_Model(answers),
            sleep=lambda _s: None,
        ),
        ProcessOptions(
            extractor="local-llm",
            batch_size=2,
            dry_run=dry_run,
            reprocess=reprocess,
            home_tz="America/New_York",
        ),
    )
    assert (code, err.getvalue()) == (0, "")
    return out.getvalue()


def _events_output(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *flags: str,
) -> str:
    monkeypatch.setattr(cli_main, "_DATA_DIR", data_dir)
    capsys.readouterr()
    with pytest.raises(SystemExit) as stop:
        cli_main.main(["events", *flags])
    assert stop.value.code == 0
    return capsys.readouterr().out


def test_consecutive_listed_days_are_separate_events_each_cited_by_its_own_mention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mails = [
        _mail(2, "SUBJ-A", f"Night Film\n{_RUN_A}\n"),
        _mail(3, "SUBJ-B", f"Night Film again\n{_MON_ONLY}\n"),
        _mail(4, "SUBJ-C", f"Night Film too\n{_RUN_B}\n"),
    ]
    answers = {
        "SUBJ-A": [_raw("Night Film", _RUN_A)],
        "SUBJ-B": [_raw("Night Film", _MON_ONLY)],
        "SUBJ-C": [_raw("Night Film", _RUN_B)],
    }
    summary = _run(tmp_path, mails, answers)
    assert "events: 4 created, 1 new mentions" in summary
    assert "rejected" not in summary.replace("rejected: 0", "")

    events = json.loads(_events_output(tmp_path, monkeypatch, capsys, "--json"))
    by_day = {e["when"][:10]: e for e in events}
    assert sorted(by_day) == ["2026-11-15", "2026-11-16", "2026-11-17", "2026-11-18"]
    assert len({e["id"] for e in events}) == 4
    sunday, monday, _tuesday, wednesday = (by_day[d] for d in sorted(by_day))
    assert [m["rung"] for m in sunday["mentions"]] == ["new"]  # Monday was NOT cited onto Sunday
    assert [m["rung"] for m in monday["mentions"]] == ["new", "title_date_venue"]
    assert {m["cites"] for m in monday["mentions"]} == {monday["id"]}
    assert [m["message_id"] for m in wednesday["mentions"]] == ["<m4@fixture.test>"]
    assert monday["showtimes"] == ["12:30", "16:00"]
    assert wednesday["showtimes"] == ["12:15", "15:45", "19:15"]
    assert sunday["showtimes"] == []


def test_message_ids_print_raw_and_are_not_stored_html_escaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(
        tmp_path,
        [_mail(2, "SUBJ-A", f"Night Film\n{_MON_ONLY}\n")],
        {"SUBJ-A": [_raw("Night Film", _MON_ONLY)]},
    )
    text = _events_output(tmp_path, monkeypatch, capsys)
    assert "<m2@fixture.test>" in text
    assert "&lt;" not in text
    assert "&lt;" not in _events_output(tmp_path, monkeypatch, capsys, "--json")
    with sqlite3.connect(tmp_path / "events" / "ledger.sqlite") as db:
        stored = [r[0] for r in db.execute("SELECT message_id FROM mentions")]
    assert stored == ["<m2@fixture.test>"]


def test_a_similar_event_on_another_date_is_a_separate_event_with_no_duplicate_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first = "Moon Party Sat Dec 12, 9pm"
    later = "The Moon Party Sat Dec 19, 9pm"
    mails = [_mail(2, "SUBJ-A", first), _mail(3, "SUBJ-B", later)]
    answers = {
        "SUBJ-A": [_raw("Moon Party", first, venue="Warehouse")],
        "SUBJ-B": [_raw("The Moon Party", later, venue="Warehouse")],
    }
    summary = _run(tmp_path, mails, answers)
    assert "2 created" in summary
    assert "0 possible duplicates" in summary

    text = _events_output(tmp_path, monkeypatch, capsys)
    assert "possible duplicate of" not in text  # other dates of a series are not duplicates
    events = json.loads(_events_output(tmp_path, monkeypatch, capsys, "--json"))
    assert all(e["possible_duplicates"] == [] for e in events)


def test_a_dry_run_and_the_real_run_agree_when_the_model_answers_the_same(tmp_path: Path) -> None:
    mails = [
        _mail(2, "SUBJ-A", f"Night Film\n{_RUN_A}\n"),
        _mail(3, "SUBJ-C", f"Night Film\n{_RUN_B}\n"),
    ]
    answers = {"SUBJ-A": [_raw("Night Film", _RUN_A)], "SUBJ-C": [_raw("Night Film", _RUN_B)]}
    dry = _run(tmp_path, mails, answers, dry_run=True)
    real = _run(tmp_path, mails, answers)
    assert _without_banner(dry) == _without_banner(real)


def _without_banner(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.startswith("DRY RUN")]


def test_reprocess_backs_up_the_old_ledger_then_starts_from_scratch(tmp_path: Path) -> None:
    mails = [_mail(2, "SUBJ-A", f"Night Film\n{_RUN_A}\n")]
    answers = {"SUBJ-A": [_raw("Night Film", _RUN_A)]}
    _run(tmp_path, mails, answers)
    ledger = tmp_path / "events" / "ledger.sqlite"
    before = ledger.read_bytes()

    out = _run(tmp_path, mails, answers, reprocess=True)

    (backup,) = (tmp_path / "events").glob("backup-*")
    assert (backup / "ledger.sqlite").read_bytes() == before  # the old file, untouched
    assert (backup / "processed.json").exists()
    assert "backed up the previous ledger" in out
    assert str(backup) in out
    assert "raw messages: 1 (0 already processed, 1 processed now" in out
    assert "events: 2 created" in out  # a fresh ledger, not 2 more on top of 2


def test_reprocess_dry_run_leaves_the_real_ledger_and_creates_no_backup(tmp_path: Path) -> None:
    mails = [_mail(2, "SUBJ-A", f"Night Film\n{_RUN_A}\n")]
    answers = {"SUBJ-A": [_raw("Night Film", _RUN_A)]}
    _run(tmp_path, mails, answers)
    ledger = tmp_path / "events" / "ledger.sqlite"
    before = ledger.read_bytes()

    out = _run(tmp_path, mails, answers, dry_run=True, reprocess=True)

    assert "events: 2 created" in out
    assert ledger.read_bytes() == before
    assert list((tmp_path / "events").glob("backup-*")) == []
