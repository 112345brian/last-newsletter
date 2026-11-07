"""fetch -> process -> build on a synthetic mailbox (fake mail source, fixed clock, tmp dirs).

No real mail, no network, no model. Asserts the stage contract: UUIDs are assigned, a second
mention of the same event cites the first event's UUID, and running everything again changes
nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from last_newsletter_adapter_publish.markdown_publisher import MarkdownPublisher
from last_newsletter_adapter_storage import (
    FileRawMessageStore,
    JsonDigestRepository,
    JsonEventRepository,
    ProcessedMarkers,
    RawStoreEmailSource,
)
from last_newsletter_adapter_summarizer.dated_line_extractor import (
    DatedLineExtractor,
    NoEmbeddedEvents,
)
from last_newsletter_adapter_summarizer.extractive_summarizer import ExtractiveSummarizer
from last_newsletter_cli.main import FetchRawResult, fetch_raw
from last_newsletter_cli.process_stage import ProcessSummary, process_raw
from last_newsletter_core.entities import Cadence, Digest, EmailMessage
from last_newsletter_core.event_ports import ExtractionFailedError
from last_newsletter_core.events import EventCandidate, EventId, MatchRule
from last_newsletter_core.use_cases import IngestEvents, IngestPorts
from last_newsletter_core.use_cases.build_digest import BuildDigestRequest, BuildDigestUseCase

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_NOW = datetime(2026, 11, 7, 12, tzinfo=UTC)
_SINCE = datetime(2026, 11, 1, tzinfo=UTC)


class _Ids:
    def new_event_id(self) -> EventId:
        return EventId(uuid4())


class _Mailbox:
    def __init__(self, messages: list[EmailMessage]) -> None:
        self._messages = messages
        self.fetches = 0

    def fetch_since(self, since: datetime) -> list[EmailMessage]:
        self.fetches += 1
        return [m for m in self._messages if m.received_at >= since]


def _mail(n: int, sender: str, body: str) -> EmailMessage:
    return EmailMessage(
        message_id=f"<m{n}@fixture.test>",
        sender=sender,
        subject=f"Newsletter {n}",
        received_at=datetime(2026, 11, n, 9, tzinfo=UTC),
        body_text=body,
        source_label=sender,
    )


_MAILBOX = [
    _mail(2, "venue@a.test", "This week:\nBand at Venue - 2026-12-12\nDoors at 8."),
    _mail(3, "promoter@b.test", "Don't miss it!\nBAND AT VENUE (2026-12-12)"),
    _mail(4, "other@c.test", "Quiz night 2026-12-20\nNo date here, just chatter."),
    _mail(5, "old@d.test", "A show that already happened 2026-01-05"),
    _mail(6, "none@e.test", "No dates at all in this one."),
]


def _ingest(tmp_path: Path) -> IngestEvents:
    return IngestEvents(
        IngestPorts(
            repository=JsonEventRepository(tmp_path / "events" / "events.json"),
            reader=NoEmbeddedEvents(),
            extractor=DatedLineExtractor(),
            ids=_Ids(),
            raw_store=FileRawMessageStore(tmp_path / "raw"),
        ),
        home_tz="UTC",
    )


def _run_all(tmp_path: Path, mailbox: _Mailbox) -> tuple[FetchRawResult, ProcessSummary, Digest]:
    store = FileRawMessageStore(tmp_path / "raw")
    fetched = fetch_raw(mailbox, store, since=_SINCE)
    processed = process_raw(
        store,
        ProcessedMarkers(tmp_path / "events" / "processed.json"),
        _ingest(tmp_path),
        now=_NOW,
        batch_size=2,
    )
    digest = BuildDigestUseCase(
        RawStoreEmailSource(store),
        ExtractiveSummarizer(),
        MarkdownPublisher(tmp_path / "markdown"),
        JsonDigestRepository(tmp_path / "digests"),
    ).execute(
        BuildDigestRequest(
            since=_SINCE, until=datetime(2026, 11, 8, tzinfo=UTC), cadence=Cadence.WEEKLY
        )
    )
    return fetched, processed, digest


def _snapshot(tmp_path: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(tmp_path)): p.read_bytes()
        for p in sorted(tmp_path.rglob("*"))
        if p.is_file() and p.name != ".lock"
    }


def test_pipeline_assigns_uuids_cites_the_first_event_and_rerun_changes_nothing(
    tmp_path: Path,
) -> None:
    fetched, processed, digest = _run_all(tmp_path, _Mailbox(_MAILBOX))

    assert (fetched.fetched, fetched.new) == (5, 5)
    assert processed.processed == 5
    result = processed.result
    assert result.created == 2  # Band at Venue + Quiz night
    assert result.mentioned == 1  # the promoter's mail cites the first event
    assert result.rejected_total == 1  # the January date is in the past
    assert result.extraction_failures == 0

    events = JsonEventRepository(tmp_path / "events" / "events.json")
    band = next(e for e in events.list_open() if e.title == "Band at Venue")
    assert isinstance(band.id, UUID)
    assert len(result.created_ids) == len(set(result.created_ids)) == 2
    assert [m.message_id for m in band.mentions] == ["<m2@fixture.test>", "<m3@fixture.test>"]
    assert band.mentions[0].match_rule is MatchRule.NEW
    assert band.mentions[1].match_rule is not MatchRule.NEW
    assert {m.cited_event_id for m in band.mentions} == {band.id}
    assert all(m.raw_ref is not None for m in band.mentions)

    assert len(digest.themes) >= 1

    before = _snapshot(tmp_path)
    mailbox = _Mailbox(_MAILBOX)
    fetched2, processed2, digest2 = _run_all(tmp_path, mailbox)

    assert (fetched2.fetched, fetched2.new) == (5, 0)
    assert (processed2.processed, processed2.already_processed) == (0, 5)
    assert processed2.result.created == 0
    assert processed2.result.mentioned == 0
    assert [t.title for t in digest2.themes] == [t.title for t in digest.themes]
    assert _snapshot(tmp_path) == before


def test_process_needs_no_mail_source_and_retries_a_failed_batch(tmp_path: Path) -> None:
    store = FileRawMessageStore(tmp_path / "raw")
    fetch_raw(_Mailbox(_MAILBOX), store, since=_SINCE)

    class _Flaky:
        def __init__(self) -> None:
            self.fail = True

        def extract(
            self, messages: Sequence[EmailMessage], *, now: datetime, home_tz: str
        ) -> list[EventCandidate]:
            if self.fail:
                msg = "model down"
                raise ExtractionFailedError(msg)
            return DatedLineExtractor().extract(messages, now=now, home_tz=home_tz)

    flaky = _Flaky()
    ingest = IngestEvents(
        IngestPorts(
            repository=JsonEventRepository(tmp_path / "events" / "events.json"),
            reader=NoEmbeddedEvents(),
            extractor=flaky,
            ids=_Ids(),
        ),
        home_tz="UTC",
    )
    markers = ProcessedMarkers(tmp_path / "events" / "processed.json")

    failed = process_raw(store, markers, ingest, now=_NOW)
    assert failed.result.extraction_failures == 5
    assert (failed.processed, failed.retry_later) == (0, 5)
    assert markers.processed() == set()

    flaky.fail = False
    ok = process_raw(store, markers, ingest, now=_NOW)
    assert ok.processed == 5
    assert ok.result.created == 2
