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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from last_newsletter_adapter_email.filtered_source import FilteredEmailSource
from last_newsletter_adapter_email.imap_source import ImapConfig, ImapEmailSource
from last_newsletter_adapter_knowledge import SqliteKnowledgeWeigher
from last_newsletter_adapter_ledger import SqliteEventRepository
from last_newsletter_adapter_publish.email_publisher import (
    CompositePublisher,
    SmtpConfig,
    SmtpEmailPublisher,
)
from last_newsletter_adapter_publish.markdown_publisher import MarkdownPublisher
from last_newsletter_adapter_storage.json_repository import JsonDigestRepository
from last_newsletter_adapter_storage.raw_message_store import (
    FileRawMessageStore,
    RawStoreEmailSource,
)
from last_newsletter_adapter_summarizer.anthropic_summarizer import AnthropicSummarizer
from last_newsletter_adapter_summarizer.extractive_summarizer import ExtractiveSummarizer
from last_newsletter_adapter_web.app import create_app
from last_newsletter_cli.build_report import BuildFacts, describe_build
from last_newsletter_cli.events_view import render_json, render_text
from last_newsletter_cli.fetch_events_command import (
    SOURCES as FETCH_EVENT_SOURCES,
)
from last_newsletter_cli.fetch_events_command import (
    FetchEventsContext,
    FetchEventsOptions,
    execute_fetch_events,
)
from last_newsletter_cli.process_command import (
    EXTRACTOR_CHOICES,
    LEDGER_NAME,
    ConfigError,
    ProcessContext,
    ProcessOptions,
    execute_process,
)
from last_newsletter_cli.process_stage import DEFAULT_BATCH_SIZE
from last_newsletter_cli.upcoming_section import UpcomingOutcome, load_upcoming
from last_newsletter_core.default_filters import DEFAULT_FILTERS
from last_newsletter_core.use_cases.list_upcoming_events import (
    DEFAULT_WINDOW_DAYS,
    MAX_WINDOW_DAYS,
)
from ranked_digest.entities import Cadence, digest_slug
from ranked_digest.use_cases.build_digest import BuildDigestRequest, BuildDigestUseCase

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from last_newsletter_adapter_storage.raw_message_store import ListableRawMessageStore
    from last_newsletter_core.use_cases.list_upcoming_events import UpcomingEvents
    from ranked_digest.ports import (
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


def _publisher(*, send: bool, upcoming: UpcomingEvents | None = None) -> DigestPublisher:
    markdown = MarkdownPublisher(output_dir=_DATA_DIR / "markdown", upcoming=upcoming)
    if not send:
        return markdown
    email = SmtpEmailPublisher(
        smtp_config_from_env(os.environ), sent_dir=_DATA_DIR / "sent", upcoming=upcoming
    )
    return CompositePublisher([markdown, email])


def _raw_store() -> FileRawMessageStore:
    return FileRawMessageStore(_DATA_DIR / "raw")


def _filtered(source: EmailSource) -> EmailSource:
    """Wraps the source in the default Gmail/Google noise filters (see default_filters.py)
    unless LAST_NEWSLETTER_DISABLE_DEFAULT_FILTERS=1, for a mailbox that is not Gmail-sourced."""
    if os.environ.get("LAST_NEWSLETTER_DISABLE_DEFAULT_FILTERS") == "1":
        return source
    return FilteredEmailSource(source, DEFAULT_FILTERS)


def _email_source() -> EmailSource:
    """The live IMAP source wrapped in the default noise filters."""
    return _filtered(_imap_source_from_env())


def _build_use_case(
    *,
    send: bool,
    summarizer: str,
    direct_imap: bool = False,
    upcoming: UpcomingEvents | None = None,
) -> BuildDigestUseCase:
    """By default the digest reads only the local raw store (filled by `fetch`): no network,
    no IMAP credentials. `direct_imap` keeps the old fetch-inside-build path."""
    email_source: EmailSource = (
        _email_source() if direct_imap else _filtered(RawStoreEmailSource(_raw_store()))
    )
    return BuildDigestUseCase(
        email_source,
        _summarizer(summarizer),
        _publisher(send=send, upcoming=upcoming),
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


def _now() -> datetime:
    """The one clock read of `build` (tests replace it)."""
    return datetime.now(tz=UTC)


@dataclass(frozen=True, slots=True)
class BuildOptions:
    """One field per `build` flag."""

    cadence: str
    send: bool = False
    summarizer: str = "extractive"
    force: bool = False
    direct_imap: bool = False
    events: bool = True
    event_days: int = DEFAULT_WINDOW_DAYS
    home_tz: str = "UTC"


def _run_build(options: BuildOptions) -> None:
    cadence = Cadence(options.cadence)
    now = _now()
    since, until = build_window(cadence, now=now, force=options.force)
    if not 1 <= options.event_days <= MAX_WINDOW_DAYS:
        msg = f"--event-days must be between 1 and {MAX_WINDOW_DAYS}"
        raise ConfigError(msg)
    try:
        ZoneInfo(options.home_tz)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        msg = f"unknown time zone {options.home_tz!r} (--home-tz or LAST_NEWSLETTER_HOME_TZ)"
        raise ConfigError(msg) from None

    # Read-only and optional: the ledger is never written here and never makes the digest fail.
    if options.events:
        outcome = load_upcoming(
            _DATA_DIR / "events" / LEDGER_NAME,
            now=now,
            days=options.event_days,
            tz_name=options.home_tz,
        )
        if outcome.warning is not None:
            sys.stderr.write(outcome.warning + "\n")
    else:
        outcome = UpcomingOutcome(None, "coming up: skipped (--no-events)")

    use_case = _build_use_case(
        send=options.send,
        summarizer=options.summarizer,
        direct_imap=options.direct_imap,
        upcoming=outcome.upcoming,
    )
    existing = {digest_slug(d) for _, d in _digest_repository().list_recent(limit=500)}
    digest = use_case.execute(BuildDigestRequest(since=since, until=until, cadence=cadence))
    raw = _raw_store()
    received = [m.received_at for ref in raw.list() if (m := raw.get(ref)) is not None]
    facts = BuildFacts(
        slug=digest_slug(digest),
        replaced=digest_slug(digest) in existing,
        force=options.force,
        raw_total=len(received),
        raw_newest=max(received, default=None),
        output_dir=str(_DATA_DIR / "markdown"),
    )
    sys.stdout.write("\n".join([*describe_build(digest, facts), outcome.line]) + "\n")


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


def _run_process(options: ProcessOptions) -> int:
    """Stage 2: reads only the local raw store; no IMAP, no cloud model, no API key."""
    context = ProcessContext(
        data_dir=_DATA_DIR,
        now=datetime.now(tz=UTC),
        environ=os.environ,
        out=sys.stdout,
        err=sys.stderr,
    )
    return execute_process(context, options)


def _run_fetch_events(options: FetchEventsOptions) -> int:
    """Stage 2b: one structured source (Ticketmaster) straight into the ledger."""
    context = FetchEventsContext(
        data_dir=_DATA_DIR,
        now=datetime.now(tz=UTC),
        environ=os.environ,
        out=sys.stdout,
        err=sys.stderr,
    )
    return execute_fetch_events(context, options)


def _run_events(*, as_json: bool) -> int:
    ledger_path = _DATA_DIR / "events" / LEDGER_NAME
    if not ledger_path.exists():
        sys.stdout.write(
            "[]\n" if as_json else "no events stored yet (run `fetch`, then `process`)\n"
        )
        return 0
    with SqliteEventRepository(ledger_path) as ledger:
        events = ledger.list_all()
    sys.stdout.write((render_json(events) if as_json else render_text(events)) + "\n")
    return 0


def _run_serve() -> None:
    """Foreground only: no background daemon, no proclaunch. You launch it (by
    double-clicking a launcher script or running this command) when you want to
    look at a digest, and close it when you're done — same as opening any other
    local app, nothing to keep alive in between."""
    app = create_app(_digest_repository())
    url = f"http://127.0.0.1:{_SERVE_PORT}/"
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.run(host="127.0.0.1", port=_SERVE_PORT, debug=False)


def _build_parser() -> argparse.ArgumentParser:
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
    build_parser.add_argument(
        "--no-events",
        action="store_true",
        help="Leave out the Coming up section (by default it lists the next --event-days days "
        "of open events from the event ledger, when one exists; read-only).",
    )
    build_parser.add_argument(
        "--event-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=f"How many calendar days the Coming up section covers, starting today "
        f"(default {DEFAULT_WINDOW_DAYS}).",
    )
    build_parser.add_argument(
        "--home-tz",
        default=os.environ.get("LAST_NEWSLETTER_HOME_TZ", "UTC"),
        help="IANA zone that decides what 'today' is for Coming up "
        "(default: $LAST_NEWSLETTER_HOME_TZ, else UTC).",
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
    process_parser.add_argument(
        "--extractor",
        choices=EXTRACTOR_CHOICES,
        default="dated-lines",
        help="dated-lines: no model (default). local-llm: a model on this machine through "
        "Ollama ($LAST_NEWSLETTER_OLLAMA_MODEL, default gpt-oss:120b; "
        "$LAST_NEWSLETTER_OLLAMA_URL, default: the local Ollama server). Nothing is sent to a "
        "cloud model.",
    )
    process_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Work on a throwaway copy of the ledger and save nothing; print only counts.",
    )
    process_parser.add_argument(
        "--reprocess",
        action="store_true",
        help="Process all stored raw mail again from an empty ledger. The old ledger, index and "
        "processed markers are moved to events/backup-<timestamp>/ first (nothing is deleted). "
        "With --dry-run nothing real is touched.",
    )
    process_parser.add_argument(
        "--home-tz",
        default=os.environ.get("LAST_NEWSLETTER_HOME_TZ", "UTC"),
        help="IANA zone for dates without one (default: $LAST_NEWSLETTER_HOME_TZ, else UTC).",
    )
    process_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)

    fetch_events_parser = subparsers.add_parser(
        "fetch-events",
        help="Fetch events from a structured source (Ticketmaster or Frequent Flyer) into the "
        "event ledger. An event already known from a newsletter or another source is cited, "
        "not duplicated.",
    )
    fetch_events_parser.add_argument(
        "--source",
        choices=FETCH_EVENT_SOURCES,
        default="ticketmaster",
        help="ticketmaster needs $TICKETMASTER_API_KEY and --city; frequentflyer needs neither "
        "(Los Angeles only); ical needs --ical-url. Times in a feed are shown in --home-tz.",
    )
    fetch_events_parser.add_argument(
        "--city", default="", help='ticketmaster only, e.g. "Los Angeles".'
    )
    fetch_events_parser.add_argument(
        "--neighborhood", default="", help='frequentflyer only, a slug such as "echo-park".'
    )
    fetch_events_parser.add_argument(
        "--ical-url", default="", help="ical only: the calendar feed (.ics) to read."
    )
    fetch_events_parser.add_argument(
        "--ical-name",
        default="",
        help="ical only: a short stable label for its mentions (default: the URL's host).",
    )
    fetch_events_parser.add_argument(
        "--ical-venue",
        default="",
        help="ical only: set when the whole feed is one venue's calendar.",
    )
    fetch_events_parser.add_argument(
        "--vibe", default="music", help='frequentflyer only (default "music"; "" for everything).'
    )
    fetch_events_parser.add_argument("--region", default="", help='State code, e.g. "CA".')
    fetch_events_parser.add_argument("--country", default="US", help="Country code (default US).")
    fetch_events_parser.add_argument(
        "--days", type=int, default=30, help="Look this many days ahead (1-365, default 30)."
    )
    fetch_events_parser.add_argument(
        "--dma-id",
        default="",
        help='Ticketmaster market id, e.g. "324" for Los Angeles: widens a city to its market.',
    )
    fetch_events_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Make the real API calls (they count against your quota) but work on a throwaway "
        "copy of the ledger and save nothing; print counts only.",
    )
    fetch_events_parser.add_argument(
        "--home-tz",
        default=os.environ.get("LAST_NEWSLETTER_HOME_TZ", "UTC"),
        help="IANA zone for 'today' and for dates without one (default: "
        "$LAST_NEWSLETTER_HOME_TZ, else UTC).",
    )

    events_parser = subparsers.add_parser(
        "events",
        help="List stored events: UUID, the mentions that cite each (message id, rung, evidence "
        "quote) and possible duplicates. No email bodies.",
    )
    events_parser.add_argument("--json", action="store_true", help="Machine-readable output.")

    subparsers.add_parser("serve", help="Open the local digest browser in your web browser.")
    return parser


def _command_build(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    try:
        _run_build(
            BuildOptions(
                cadence=args.cadence,
                send=args.send,
                summarizer=args.summarizer,
                force=args.force,
                direct_imap=args.imap,
                events=not args.no_events,
                event_days=args.event_days,
                home_tz=args.home_tz,
            )
        )
    except ConfigError as error:
        parser.exit(2, f"last-newsletter: {error}\n")


def _command_fetch(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    try:
        _run_fetch(since=args.since, days=args.days, out=args.out)
    except ConfigError as error:
        parser.exit(2, f"last-newsletter: {error}\n")


def _command_process(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    try:
        code = _run_process(
            ProcessOptions(
                extractor=args.extractor,
                home_tz=args.home_tz,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
                reprocess=args.reprocess,
            )
        )
    except (ConfigError, TimeoutError) as error:
        parser.exit(2, f"last-newsletter: {error}\n")
    if code:
        sys.exit(code)


def _command_fetch_events(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    try:
        code = _run_fetch_events(
            FetchEventsOptions(
                source=args.source,
                city=args.city,
                region=args.region,
                country=args.country,
                days=args.days,
                dma_id=args.dma_id,
                neighborhood=args.neighborhood,
                vibe=args.vibe,
                ical_url=args.ical_url,
                ical_name=args.ical_name,
                ical_venue=args.ical_venue,
                home_tz=args.home_tz,
                dry_run=args.dry_run,
            )
        )
    except (ConfigError, TimeoutError) as error:
        parser.exit(2, f"last-newsletter: {error}\n")
    if code:
        sys.exit(code)


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "build":
        _command_build(parser, args)
    elif args.command == "fetch":
        _command_fetch(parser, args)
    elif args.command == "process":
        _command_process(parser, args)
    elif args.command == "fetch-events":
        _command_fetch_events(parser, args)
    elif args.command == "events":
        sys.exit(_run_events(as_json=args.json))
    elif args.command == "serve":
        _run_serve()


if __name__ == "__main__":
    main()
