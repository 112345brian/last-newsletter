"""fetch -> process (local model, SQLite ledger, semantic index) -> events -> digest, over a small
synthetic mailbox. The model is a fake Ollama transport; the clock is fixed; no network."""

from __future__ import annotations

import importlib
import io
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from last_newsletter_adapter_publish.markdown_publisher import MarkdownPublisher
from last_newsletter_adapter_storage import (
    FileRawMessageStore,
    JsonDigestRepository,
    RawStoreEmailSource,
)
from last_newsletter_adapter_summarizer.extractive_summarizer import ExtractiveSummarizer
from last_newsletter_cli.main import fetch_raw
from last_newsletter_cli.process_command import ProcessContext, ProcessOptions, execute_process
from ranked_digest.entities import Cadence, EmailMessage
from ranked_digest.use_cases.build_digest import BuildDigestRequest, BuildDigestUseCase

if TYPE_CHECKING:
    from pathlib import Path

# `last_newsletter_cli.main` the attribute is the entry-point function; we want the module.
cli_main = importlib.import_module("last_newsletter_cli.main")

_NOW = datetime(2026, 11, 7, 12, tzinfo=UTC)
_SINCE = datetime(2026, 11, 1, tzinfo=UTC)
_ENV = {"LAST_NEWSLETTER_OLLAMA_MODEL": "fake-model"}


def _mail(n: int, subject: str, body: str) -> EmailMessage:
    return EmailMessage(
        message_id=f"<m{n}@fixture.test>",
        sender=f"sender{n}@fixture.test",
        subject=subject,
        received_at=datetime(2026, 11, n, 9, tzinfo=UTC),
        body_text=body,
        source_label=f"sender{n}@fixture.test",
    )


_MAILBOX = [
    _mail(2, "SUBJ-A", "This week: Moon Party Sat Dec 12, 9pm at the Warehouse. Doors at 8."),
    _mail(3, "SUBJ-B", "Don't miss it! Moon Party Sat Dec 12, 9pm at the Warehouse."),
    _mail(4, "SUBJ-C", "New this month: The Moon Party Sat Dec 12, 11pm, Warehouse, all night."),
    _mail(5, "SUBJ-D", "Quiz Night Sun Dec 20, 7pm at the Pub."),
    _mail(6, "SUBJ-E", "No dates in this one, just chatter."),
]

# subject marker -> what the fake model answers for that email
_ANSWERS: dict[str, dict[str, str]] = {
    "SUBJ-A": {"title": "Moon Party", "start": "Sat Dec 12, 9pm", "venue": "Warehouse"},
    "SUBJ-B": {"title": "Moon Party", "start": "Sat Dec 12, 9pm", "venue": "Warehouse"},
    "SUBJ-C": {"title": "The Moon Party", "start": "Sat Dec 12, 11pm", "venue": "Warehouse"},
    "SUBJ-D": {"title": "Quiz Night", "start": "Sun Dec 20, 7pm", "venue": "Pub"},
}


class FakeOllama:
    """Answers each chat call from the subject marker in the prompt; counts the calls."""

    def __init__(self, *, down: bool = False) -> None:
        self.down = down
        self.calls = 0

    def post(self, url: str, body: bytes, *, timeout_s: float) -> tuple[int, bytes]:
        self.calls += 1
        if self.down:
            raise ConnectionRefusedError
        prompt = json.loads(body)["messages"][1]["content"]
        answer = next((a for key, a in _ANSWERS.items() if key in prompt), None)
        events: list[dict[str, Any]] = []
        if answer is not None:
            evidence = f"{answer['title']} {answer['start']}"
            events.append(
                {
                    "title": answer["title"],
                    "kind": "event",
                    "start_text": answer["start"],
                    "end_text": "",
                    "venue": answer["venue"],
                    "cancelled": False,
                    "confidence": "high",
                    "evidence": evidence,
                }
            )
        content = json.dumps({"events": events})
        return 200, json.dumps({"message": {"role": "assistant", "content": content}}).encode()


class _Mailbox:
    def fetch_since(self, since: datetime) -> list[EmailMessage]:
        return [m for m in _MAILBOX if m.received_at >= since]


def _no_sleep(_s: float) -> None:
    return None


def _process(
    data_dir: Path, ollama: FakeOllama, *, dry_run: bool = False, extractor: str = "local-llm"
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = execute_process(
        ProcessContext(
            data_dir=data_dir,
            now=_NOW,
            environ=_ENV,
            out=out,
            err=err,
            transport=ollama,
            sleep=_no_sleep,
        ),
        ProcessOptions(extractor=extractor, batch_size=2, dry_run=dry_run),
    )
    return code, out.getvalue(), err.getvalue()


def _fetch(data_dir: Path) -> None:
    fetch_raw(_Mailbox(), FileRawMessageStore(data_dir / "raw"), since=_SINCE)


def _events(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> list[dict[str, Any]]:
    monkeypatch.setattr(cli_main, "_DATA_DIR", data_dir)
    capsys.readouterr()
    with pytest.raises(SystemExit) as stop:
        cli_main.main(["events", "--json"])
    assert stop.value.code == 0
    return json.loads(capsys.readouterr().out)


def _by_title(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {e["title"]: e for e in events}


def test_fetch_process_events_digest_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fetch(tmp_path)
    code, out, err = _process(tmp_path, FakeOllama())
    assert (code, err) == (0, "")
    assert "raw messages: 5" in out
    assert "5 processed now" in out

    events = _events(tmp_path, monkeypatch, capsys)
    by_title = _by_title(events)
    assert set(by_title) == {"Moon Party", "The Moon Party", "Quiz Night"}

    # A second mention of the same event cites the first UUID, via a deterministic rung.
    moon = by_title["Moon Party"]
    assert [m["message_id"] for m in moon["mentions"]] == ["<m2@fixture.test>", "<m3@fixture.test>"]
    assert {m["cites"] for m in moon["mentions"]} == {moon["id"]}
    assert [m["rung"] for m in moon["mentions"]] == ["new", "title_date_venue"]
    assert all(m["evidence"] for m in moon["mentions"])

    # Same date, related title, but a different showtime: a new event linked as a possible
    # duplicate (not cited, not merged); the link shows from both sides.
    near = by_title["The Moon Party"]
    assert near["id"] != moon["id"]
    assert [d["id"] for d in near["possible_duplicates"]] == [moon["id"]]
    assert [d["id"] for d in moon["possible_duplicates"]] == [near["id"]]
    assert by_title["Quiz Night"]["possible_duplicates"] == []

    # The listing never carries a message body, only the stored evidence quote.
    assert "Doors at 8" not in json.dumps(events)

    digest = BuildDigestUseCase(
        RawStoreEmailSource(FileRawMessageStore(tmp_path / "raw")),
        ExtractiveSummarizer(),
        MarkdownPublisher(tmp_path / "markdown"),
        JsonDigestRepository(tmp_path / "digests"),
    ).execute(
        BuildDigestRequest(
            since=_SINCE, until=datetime(2026, 11, 8, tzinfo=UTC), cadence=Cadence.WEEKLY
        )
    )
    assert digest.total_messages == 5
    assert list((tmp_path / "markdown").glob("*.md"))


def test_rerun_changes_nothing_and_asks_the_model_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fetch(tmp_path)
    _process(tmp_path, FakeOllama())
    before = _events(tmp_path, monkeypatch, capsys)
    markers = (tmp_path / "events" / "processed.json").read_bytes()

    second = FakeOllama()
    code, out, _ = _process(tmp_path, second)

    assert code == 0
    assert second.calls == 0
    assert "5 already processed" in out
    assert _events(tmp_path, monkeypatch, capsys) == before
    assert (tmp_path / "events" / "processed.json").read_bytes() == markers


def test_ollama_down_leaves_messages_unprocessed_and_exits_nonzero(tmp_path: Path) -> None:
    _fetch(tmp_path)
    down = FakeOllama(down=True)
    code, out, err = _process(tmp_path, down)

    assert code == 1
    assert "Is Ollama running" in err
    assert "fake-model" in err
    assert "0 processed now" in out
    assert not (tmp_path / "events" / "processed.json").exists()

    # Back up: the very same messages are picked up and ingested.
    code, out, err = _process(tmp_path, FakeOllama())
    assert (code, err) == (0, "")
    assert "5 processed now" in out


def test_dry_run_prints_counts_and_saves_nothing(tmp_path: Path) -> None:
    _fetch(tmp_path)
    _process(tmp_path, FakeOllama(), extractor="dated-lines")  # an existing ledger to copy

    def state() -> dict[str, bytes]:
        return {
            str(p.relative_to(tmp_path)): p.read_bytes()
            for p in sorted(tmp_path.rglob("*"))
            if p.is_file() and not p.name.endswith(".lock")
        }

    before = state()
    code, out, err = _process(tmp_path, FakeOllama(), dry_run=True)
    assert (code, err) == (0, "")
    assert out.startswith("DRY RUN")
    assert state() == before


def test_dry_run_on_a_fresh_data_dir_creates_nothing(tmp_path: Path) -> None:
    _fetch(tmp_path)
    raw_only = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file()}
    code, out, _ = _process(tmp_path, FakeOllama(), dry_run=True)
    assert code == 0
    assert "5 processed now" in out  # what a real run would do
    now_files = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file()}
    assert now_files == raw_only
    assert not (tmp_path / "events").exists()


def test_events_listing_on_an_empty_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _events(tmp_path, monkeypatch, capsys) == []
    with pytest.raises(SystemExit):
        cli_main.main(["events"])
    assert "no events stored yet" in capsys.readouterr().out


def test_events_text_listing_shows_uuid_mentions_and_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fetch(tmp_path)
    _process(tmp_path, FakeOllama())
    monkeypatch.setattr(cli_main, "_DATA_DIR", tmp_path)
    capsys.readouterr()
    with pytest.raises(SystemExit):
        cli_main.main(["events"])
    text = capsys.readouterr().out
    assert "mention <m3@fixture.test>  rung=title_date_venue" in text
    assert "possible duplicate of" in text
