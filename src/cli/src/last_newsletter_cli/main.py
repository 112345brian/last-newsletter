"""Composition root. Wires concrete adapters into the core use case and runs it.

This is the only module in the workspace allowed to import from every other
package. Nothing downstream of this file should ever import `last_newsletter_cli`.
"""

from __future__ import annotations

__arbor__ = {"ring": "cli"}

import argparse
import os
import sys
import threading
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from process_lock.file_lock import cross_process_file_lock

from last_newsletter_adapter_email.imap_source import ImapConfig, ImapEmailSource
from last_newsletter_adapter_knowledge import SqliteKnowledgeWeigher
from last_newsletter_adapter_publish.email_publisher import (
    CompositePublisher,
    SmtpConfig,
    SmtpEmailPublisher,
)
from last_newsletter_adapter_publish.markdown_publisher import MarkdownPublisher
from last_newsletter_adapter_storage.json_event_repository import JsonEventRepository
from last_newsletter_adapter_storage.json_repository import JsonDigestRepository
from last_newsletter_adapter_storage.processed_markers import ProcessedMarkers
from last_newsletter_adapter_storage.raw_message_store import (
    FileRawMessageStore,
    RawStoreEmailSource,
)
from last_newsletter_adapter_summarizer.anthropic_summarizer import AnthropicSummarizer
from last_newsletter_adapter_summarizer.dated_line_extractor import (
    DatedLineExtractor,
    NoEmbeddedEvents,
)
from last_newsletter_adapter_summarizer.extractive_summarizer import ExtractiveSummarizer
from last_newsletter_adapter_web.app import create_app
from last_newsletter_cli.process_stage import DEFAULT_BATCH_SIZE, process_raw
from last_newsletter_core.entities import Cadence
from last_newsletter_core.events import EventId
from last_newsletter_core.use_cases import IngestEvents, IngestPorts
from last_newsletter_core.use_cases.build_digest import BuildDigestRequest, BuildDigestUseCase

if TYPE_CHECKING:
    from collections.abc import Mapping

    from last_newsletter_adapter_storage.raw_message_store import ListableRawMessageStore
    from last_newsletter_core.event_ports import EventExtractor, EventRepository
    from last_newsletter_core.ports import (
        DigestPublisher,
        EmailSource,
        RelevanceWeigher,
        Summarizer,
    )

_DATA_DIR = Path.home() / ".last-newsletter"
_SERVE_PORT = 5317
_FETCH_OVERLAP = timedelta(days=1)


def _digest_repository() -> JsonDigestRepository:
    return JsonDigestRepository(_DATA_DIR / "digests")


def _configured_weighers() -> list[RelevanceWeigher]:
    """Entirely opt-in: the generic program runs with none of these configured,
    and nothing about BuildDigestUseCase changes either way. Set
    LAST_NEWSLETTER_KNOWLEDGE_DB_PATH to turn this one on; add another env var
    and another `if` here for a future weigher, never by changing core."""
    weighers: list[RelevanceWeigher] = []
    knowledge_db_path = os.environ.get("LAST_NEWSLETTER_KNOWLEDGE_DB_PATH")
    if bool(knowledge_db_path):
        weighers.append(
            SqliteKnowledgeWeigher(
                Path(knowledge_db_path).expanduser(),
                subject_name=os.environ.get("LAST_NEWSLETTER_KNOWLEDGE_SUBJECT"),
            )
        )
    return weighers


class ConfigError(Exception):
    """A setting is missing or invalid. Its message names the variable to fix."""


def smtp_config_from_env(environ: Mapping[str, str]) -> SmtpConfig:
    def required(name: str) -> str:
        value = environ.get(name, "").strip()
        if not value:
            msg = f"{name} is not set"
            raise ConfigError(msg)
        return value

    host = required("LAST_NEWSLETTER_SMTP_HOST")
    username = required("LAST_NEWSLETTER_SMTP_USER")
    password = required("LAST_NEWSLETTER_SMTP_PASSWORD")
    port_text = environ.get("LAST_NEWSLETTER_SMTP_PORT", "465")
    try:
        port = int(port_text)
    except ValueError:
        msg = f"LAST_NEWSLETTER_SMTP_PORT must be a number, got {port_text!r}"
        raise ConfigError(msg) from None
    sender = environ.get("LAST_NEWSLETTER_SMTP_FROM", username)
    try:
        return SmtpConfig(
            host=host,
            port=port,
            username=username,
            password=password,
            sender=sender,
            recipient=environ.get("LAST_NEWSLETTER_SMTP_TO", sender),
            use_ssl=environ.get("LAST_NEWSLETTER_SMTP_SSL", "1") != "0",
        )
    except ValueError as error:
        raise ConfigError(str(error)) from error


def _summarizer(name: str) -> Summarizer:
    if name == "anthropic":
        return AnthropicSummarizer(
            provider=os.environ.get("LAST_NEWSLETTER_LLM_PROVIDER", "claude"),
            usage_ledger_path=_DATA_DIR / "usage.jsonl",
        )
    return ExtractiveSummarizer()


def _publisher(*, send: bool) -> DigestPublisher:
    markdown = MarkdownPublisher(output_dir=_DATA_DIR / "markdown")
    if not send:
        return markdown
    email = SmtpEmailPublisher(smtp_config_from_env(os.environ), sent_dir=_DATA_DIR / "sent")
    return CompositePublisher([markdown, email])


def _raw_store() -> FileRawMessageStore:
    return FileRawMessageStore(_DATA_DIR / "raw")


def _build_use_case(
    *, send: bool, summarizer: str, direct_imap: bool = False
) -> BuildDigestUseCase:
    """By default the digest reads only the local raw store (filled by `fetch`): no network,
    no IMAP credentials. `direct_imap` keeps the old fetch-inside-build path."""
    email_source: EmailSource = (
        _imap_source_from_env() if direct_imap else RawStoreEmailSource(_raw_store())
    )
    return BuildDigestUseCase(
        email_source,
        _summarizer(summarizer),
        _publisher(send=send),
        _digest_repository(),
        weighers=_configured_weighers(),
    )


def build_window(
    cadence: Cadence, *, now: datetime, force: bool = False
) -> tuple[datetime, datetime]:
    """The `(since, until)` window for one build. Aligned to UTC midnight, not `now`, by
    default: a re-run later the same day is still the same period (same slug, overwritten
    in place) instead of a new overlapping one that double-counts streaks. `force` breaks
    that alignment deliberately -- it's for confirming the pipeline works right now during
    setup, not for the normal daily/weekly schedule."""
    until = now if force else now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = until - (timedelta(days=1) if cadence is Cadence.DAILY else timedelta(days=7))
    return since, until


def _run_build(
    cadence_name: str,
    *,
    send: bool,
    summarizer: str,
    force: bool = False,
    direct_imap: bool = False,
) -> None:
    cadence = Cadence(cadence_name)
    since, until = build_window(cadence, now=datetime.now(tz=UTC), force=force)

    use_case = _build_use_case(send=send, summarizer=summarizer, direct_imap=direct_imap)
    use_case.execute(BuildDigestRequest(since=since, until=until, cadence=cadence))


@dataclass(frozen=True, slots=True)
class FetchRawResult:
    fetched: int
    new: int

    @property
    def already_stored(self) -> int:
        return self.fetched - self.new


def fetch_raw(
    source: EmailSource, store: ListableRawMessageStore, *, since: datetime
) -> FetchRawResult:
    """Copy every message from `source` since `since` into `store`. Idempotent: a message
    already stored (same id) is left untouched and counted as `already_stored`."""
    existing = set(store.list())
    messages = source.fetch_since(since)
    new_refs = {store.put(message) for message in messages} - existing
    return FetchRawResult(fetched=len(messages), new=len(new_refs))


def raw_since(
    *,
    since: str | None,
    days: int | None,
    now: datetime,
    watermark: datetime | None = None,
) -> datetime:
    """Where a fetch starts. Explicit `--since YYYY-MM-DD` (UTC midnight) or `--days N` win.
    Otherwise resume from the last successful fetch's start minus a day of overlap (re-fetching
    is idempotent, a gap is not); with no watermark yet, the last 7 days."""
    if since is not None and days is not None:
        msg = "use either --since or --days, not both"
        raise ConfigError(msg)
    if since is not None:
        try:
            return datetime.fromisoformat(since).replace(tzinfo=UTC)
        except ValueError:
            msg = f"--since must be YYYY-MM-DD, got {since!r}"
            raise ConfigError(msg) from None
    if days is None and watermark is not None:
        return watermark - _FETCH_OVERLAP
    days = 7 if days is None else days
    if days < 1:
        msg = "--days must be at least 1"
        raise ConfigError(msg)
    return now - timedelta(days=days)


def _imap_source_from_env() -> ImapEmailSource:
    try:
        return ImapEmailSource(
            ImapConfig(
                host=os.environ["LAST_NEWSLETTER_IMAP_HOST"],
                username=os.environ["LAST_NEWSLETTER_IMAP_USER"],
                password=os.environ["LAST_NEWSLETTER_IMAP_PASSWORD"],
            )
        )
    except KeyError as error:
        msg = f"{error.args[0]} is not set"
        raise ConfigError(msg) from None


def _run_fetch(*, since: str | None, days: int | None, out: Path | None) -> None:
    started = datetime.now(tz=UTC)
    store = FileRawMessageStore(out if out is not None else _DATA_DIR / "raw")
    window_start = raw_since(since=since, days=days, now=started, watermark=store.read_watermark())
    result = fetch_raw(_imap_source_from_env(), store, since=window_start)
    # Only after a fully successful fetch: a failure above leaves the old watermark in place.
    store.write_watermark(started)
    sys.stdout.write(
        f"fetched {result.fetched} message(s) since {window_start.isoformat()}: "
        f"{result.new} new, {result.already_stored} already stored\n"
    )


class Uuid4Ids:
    """`IdGenerator`: random UUIDs (randomness is an effect, so it lives outside core)."""

    def new_event_id(self) -> EventId:
        return EventId(uuid4())


def _event_repository() -> EventRepository:
    # SEAM: file-backed ledger for now. The SQLite `EventRepository` adapter replaces this one
    # line; the port (`last_newsletter_core.event_ports.EventRepository`) is the contract.
    return JsonEventRepository(_DATA_DIR / "events" / "events.json")


def _extractor(name: str) -> EventExtractor:
    # SEAM: `--extractor local-llm` (src/adapter_events) plugs in here. Anything that costs
    # money must stay behind its own explicit flag; the default is model-free.
    if name == "dated-lines":
        return DatedLineExtractor()
    msg = f"unknown extractor {name!r}"
    raise ConfigError(msg)


def _ingest_use_case(*, extractor: str, home_tz: str) -> IngestEvents:
    # SEAM: pass `similar_index=` here to use the semantic index (src/adapter_semantic,
    # `SimilarEventIndex`). Without it core uses its difflib default, seeded per run.
    return IngestEvents(
        IngestPorts(
            repository=_event_repository(),
            reader=NoEmbeddedEvents(),
            extractor=_extractor(extractor),
            ids=Uuid4Ids(),
            raw_store=_raw_store(),
        ),
        home_tz=home_tz,
    )


def _run_process(*, extractor: str, home_tz: str, batch_size: int) -> None:
    """Stage 2: reads only the local raw store; no IMAP, no network."""
    with cross_process_file_lock(_DATA_DIR / "process.lock", timeout_s=5.0, label="process"):
        summary = process_raw(
            _raw_store(),
            ProcessedMarkers(_DATA_DIR / "events" / "processed.json"),
            _ingest_use_case(extractor=extractor, home_tz=home_tz),
            now=datetime.now(tz=UTC),
            batch_size=batch_size,
        )
    sys.stdout.write("\n".join(summary.lines()) + "\n")


def _run_serve() -> None:
    """Foreground only: no background daemon, no proclaunch. You launch it (by
    double-clicking a launcher script or running this command) when you want to
    look at a digest, and close it when you're done — same as opening any other
    local app, nothing to keep alive in between."""
    app = create_app(_digest_repository())
    url = f"http://127.0.0.1:{_SERVE_PORT}/"
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.run(host="127.0.0.1", port=_SERVE_PORT, debug=False)


def main() -> None:
    parser = argparse.ArgumentParser(prog="last-newsletter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Fetch mail and write a new digest.")
    build_parser.add_argument("--cadence", choices=["daily", "weekly"], default="weekly")
    build_parser.add_argument(
        "--send",
        action="store_true",
        help="Also email the digest (needs the LAST_NEWSLETTER_SMTP_* variables). "
        "A period is emailed at most once.",
    )
    build_parser.add_argument(
        "--summarizer",
        choices=["extractive", "anthropic"],
        default="extractive",
        help="extractive: no model, excerpts of each email (default).",
    )
    build_parser.add_argument(
        "--imap",
        action="store_true",
        help="Read mail straight from IMAP instead of the local raw store (needs the "
        "LAST_NEWSLETTER_IMAP_* variables). Default: read the raw store filled by `fetch`.",
    )
    build_parser.add_argument(
        "--force",
        action="store_true",
        help="Dev/testing only: also include messages from today, breaking the normal "
        "midnight-aligned period. Use this to confirm the pipeline works right now during "
        "setup, not for the regular daily/weekly schedule.",
    )

    raw_parser = subparsers.add_parser(
        "fetch",
        help="Stage 1: append new mail from IMAP to the local raw store (no digest, no model). "
        "Incremental from the last run; safe to schedule.",
    )
    raw_parser.add_argument(
        "--since", help="Start date, YYYY-MM-DD (UTC); overrides the watermark."
    )
    raw_parser.add_argument(
        "--days",
        type=int,
        help="Look back this many days; overrides the watermark (default: resume, else 7).",
    )
    raw_parser.add_argument(
        "--out", type=Path, help=f"Directory to write to (default {_DATA_DIR / 'raw'})."
    )

    process_parser = subparsers.add_parser(
        "process",
        help="Stage 2: turn stored raw mail into event records (UUID per event, later mentions "
        "cite the first). Reads only the local raw store: no IMAP, no network. Re-runnable.",
    )
    process_parser.add_argument("--extractor", choices=["dated-lines"], default="dated-lines")
    process_parser.add_argument(
        "--home-tz",
        default=os.environ.get("LAST_NEWSLETTER_HOME_TZ", "UTC"),
        help="IANA zone for dates without one (default: $LAST_NEWSLETTER_HOME_TZ, else UTC).",
    )
    process_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)

    subparsers.add_parser("serve", help="Open the local digest browser in your web browser.")

    args = parser.parse_args()
    if args.command == "build":
        try:
            _run_build(
                args.cadence,
                send=args.send,
                summarizer=args.summarizer,
                force=args.force,
                direct_imap=args.imap,
            )
        except ConfigError as error:
            parser.exit(2, f"last-newsletter: {error}\n")
    elif args.command == "fetch":
        try:
            _run_fetch(since=args.since, days=args.days, out=args.out)
        except ConfigError as error:
            parser.exit(2, f"last-newsletter: {error}\n")
    elif args.command == "process":
        try:
            _run_process(extractor=args.extractor, home_tz=args.home_tz, batch_size=args.batch_size)
        except (ConfigError, TimeoutError) as error:
            parser.exit(2, f"last-newsletter: {error}\n")
    elif args.command == "serve":
        _run_serve()


if __name__ == "__main__":
    main()
