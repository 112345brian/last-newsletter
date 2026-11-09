"""The `fetch-events` command: one structured source straight into the event ledger.

The same shape as `process`: everything ambient (data directory, environment, clock, HTTP
client, id source) is handed in by `main`, so tests drive the exact code with a temp directory,
a fixed clock and a scripted `httpx` transport. The network is used first and the ledger lock
second, so a slow API never holds up `process`. Output is counts only (plus any attribution a
source requires): no titles, venues, or keys.

This module is the composition root for sources: it is the only place that knows which sources
exist and what each needs. Adding one is a new adapter, a branch in `_build_source`, and its flags.
"""

from __future__ import annotations

__arbor__ = {"ring": "cli"}

import time
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from last_newsletter_adapter_frequentflyer import (
    FrequentFlyerClient,
    FrequentFlyerConfig,
    FrequentFlyerEventSource,
)
from last_newsletter_adapter_ical import IcalClient, IcalConfig, IcalEventSource
from last_newsletter_adapter_ticketmaster import (
    TicketmasterClient,
    TicketmasterConfig,
    TicketmasterEventSource,
)
from last_newsletter_cli.command_support import ConfigError, Uuid4Ids, ledger_session
from last_newsletter_cli.similarity import LINK_ONLY_POLICY, CoreSimilarIndex
from last_newsletter_core.event_ports import SourceFetchError, SourceWindow
from last_newsletter_core.use_cases import IngestSourceEvents, SourceIngestPorts

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import datetime
    from pathlib import Path
    from typing import TextIO

    import httpx

    from last_newsletter_cli.command_support import IdGenerator
    from last_newsletter_core.event_ports import EventSource, SourceReport

SOURCES = ("ticketmaster", "frequentflyer", "ical")
TICKETMASTER_KEY = "TICKETMASTER_API_KEY"
MAX_DAYS = 365


@dataclass(frozen=True, slots=True)
class FetchEventsContext:
    data_dir: Path
    now: datetime
    environ: Mapping[str, str]
    out: TextIO
    err: TextIO
    ids: IdGenerator | None = None
    http: httpx.Client | None = None
    sleep: Callable[[float], None] | None = None


@dataclass(frozen=True, slots=True)
class FetchEventsOptions:
    source: str = "ticketmaster"
    days: int = 30
    home_tz: str = "UTC"
    dry_run: bool = False
    # ticketmaster
    city: str = ""
    region: str = ""
    country: str = "US"
    dma_id: str = ""
    # frequentflyer
    neighborhood: str = ""
    vibe: str = "music"
    # ical: any published calendar; the name labels its mentions and defaults to the URL's host
    ical_url: str = ""
    ical_name: str = ""
    ical_venue: str = ""


def _window(ctx: FetchEventsContext, options: FetchEventsOptions) -> SourceWindow:
    if not 1 <= options.days <= MAX_DAYS:
        msg = f"--days must be between 1 and {MAX_DAYS}"
        raise ConfigError(msg)
    try:
        zone = ZoneInfo(options.home_tz)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        msg = f"unknown time zone {options.home_tz!r} (--home-tz or LAST_NEWSLETTER_HOME_TZ)"
        raise ConfigError(msg) from None
    today = ctx.now.astimezone(zone).date()
    return SourceWindow(date_from=today, date_to=today + timedelta(days=options.days))


def _build_source(ctx: FetchEventsContext, options: FetchEventsOptions) -> EventSource:
    if options.source == "ticketmaster":
        key = ctx.environ.get(TICKETMASTER_KEY, "").strip()
        if not key:
            msg = f"{TICKETMASTER_KEY} is not set (a free key: https://developer.ticketmaster.com)"
            raise ConfigError(msg)
        if not options.city.strip():
            msg = "--city is required for the ticketmaster source"
            raise ConfigError(msg)
        client = TicketmasterClient(key, http=ctx.http, sleep=ctx.sleep or time.sleep)
        return TicketmasterEventSource(
            client,
            TicketmasterConfig(
                city=options.city.strip(),
                region=options.region.strip(),
                country=options.country.strip() or "US",
                dma_id=options.dma_id.strip(),
            ),
        )
    if options.source == "frequentflyer":
        return FrequentFlyerEventSource(
            FrequentFlyerClient(http=ctx.http),
            FrequentFlyerConfig(
                vibe=options.vibe.strip(), neighborhood=options.neighborhood.strip()
            ),
        )
    if options.source == "ical":
        return _ical_source(ctx, options)
    msg = f"unknown source {options.source!r} (one of: {', '.join(SOURCES)})"
    raise ConfigError(msg)


def _ical_source(ctx: FetchEventsContext, options: FetchEventsOptions) -> EventSource:
    url = options.ical_url.strip()
    if urlsplit(url).scheme not in {"http", "https"}:
        msg = "--ical-url must be an http or https URL for the ical source"
        raise ConfigError(msg)
    name = options.ical_name.strip() or (urlsplit(url).hostname or "ical")
    return IcalEventSource(
        IcalClient(http=ctx.http),
        IcalConfig(name=name, url=url, tz=options.home_tz, venue=options.ical_venue.strip()),
    )


def execute_fetch_events(ctx: FetchEventsContext, options: FetchEventsOptions) -> int:
    """Fetch, ingest, and print counts. Returns the exit code: 0 on success, 1 when the fetch
    failed (nothing was written; a rerun is safe)."""
    source = _build_source(ctx, options)
    window = _window(ctx, options)
    try:
        batch = source.fetch(window, now=ctx.now)
    except SourceFetchError as error:
        ctx.err.write(f"last-newsletter: {error}; nothing was saved, a rerun is safe\n")
        return 1

    with ledger_session(ctx.data_dir, dry_run=options.dry_run) as session:
        session.sync_index()
        result = IngestSourceEvents(
            source.name,
            SourceIngestPorts(
                repository=session.ledger,
                ids=ctx.ids or Uuid4Ids(),
                similar_index=CoreSimilarIndex(session.index),
            ),
            home_tz=options.home_tz,
            policy=LINK_ONLY_POLICY,
        ).ingest_batch(batch, now=ctx.now)
    header = (
        f"{source.name}: {len(batch.candidates)} event(s), "
        f"{window.date_from.isoformat()} to {window.date_to.isoformat()} "
        f"({batch.report.requests} request(s))"
    )
    tally = (
        f"events: {result.created} created, {result.mentioned} new mentions, "
        f"{result.unchanged} unchanged, {result.possible_duplicates} possible duplicates"
    )
    lines = [*session.notes, header, *_report_lines(batch.report), tally]
    if result.rejected_total:
        reasons = ", ".join(f"{r.value} {n}" for r, n in sorted(result.rejected.items()))
        lines.append(f"rejected: {result.rejected_total} ({reasons})")
    ctx.out.write("\n".join(lines) + "\n")
    return 0


def _report_lines(report: SourceReport) -> list[str]:
    lines: list[str] = []
    if report.skipped:
        reasons = ", ".join(f"{reason} {n}" for reason, n in sorted(report.skipped.items()))
        lines.append(f"skipped: {reasons}")
    if report.outside_window:
        lines.append(f"outside the requested dates: {report.outside_window}")
    if report.truncated:
        lines.append(
            f"WARNING: {report.truncated} match(es) the source reported were not fetched "
            "(its paging cap); narrow the search (--days, or a source filter)"
        )
    lines.extend(f"note: {note}" for note in report.notes)
    return lines
