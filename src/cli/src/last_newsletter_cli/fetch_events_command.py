"""The `fetch-events` command: one structured source (Ticketmaster) into the event ledger.

The same shape as `process`: everything ambient (data directory, environment, clock, HTTP
transport, id source) is handed in by `main`, so tests drive the exact code with a temp
directory, a fixed clock and a scripted transport. The network is used first and the ledger
lock second, so a slow API never holds up `process`. Output is counts only: no titles, venues,
or key.
"""

from __future__ import annotations

__arbor__ = {"ring": "cli"}

import time
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from last_newsletter_adapter_ticketmaster import (
    TicketmasterClient,
    TicketmasterConfig,
    TicketmasterEventSource,
)
from last_newsletter_cli.command_support import ConfigError, Uuid4Ids, ledger_session
from last_newsletter_cli.similarity import LINK_ONLY_POLICY, CoreSimilarIndex
from last_newsletter_core.event_ports import SourceFetchError, SourceQuery
from last_newsletter_core.use_cases import IngestSourceEvents, SourceIngestPorts

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import datetime
    from pathlib import Path
    from typing import TextIO

    from http_transport import Getter
    from last_newsletter_adapter_ticketmaster import FetchStats
    from last_newsletter_cli.command_support import IdGenerator
    from last_newsletter_core.events import EventCandidate

KEY_VARIABLE = "TICKETMASTER_API_KEY"
MAX_DAYS = 365


@dataclass(frozen=True, slots=True)
class FetchEventsContext:
    data_dir: Path
    now: datetime
    environ: Mapping[str, str]
    out: TextIO
    err: TextIO
    ids: IdGenerator | None = None
    transport: Getter | None = None
    sleep: Callable[[float], None] | None = None


@dataclass(frozen=True, slots=True)
class FetchEventsOptions:
    city: str
    region: str = ""
    country: str = "US"
    days: int = 30
    dma_id: str = ""
    home_tz: str = "UTC"
    dry_run: bool = False


class _Fetched:
    """An `EventSource` over candidates already fetched, so the ledger lock is taken only after
    the slow network part is over."""

    def __init__(self, name: str, candidates: list[EventCandidate]) -> None:
        self._name = name
        self._candidates = candidates

    @property
    def name(self) -> str:
        return self._name

    def fetch(self, query: SourceQuery, *, now: datetime) -> list[EventCandidate]:
        _ = (query, now)
        return list(self._candidates)


def _query(ctx: FetchEventsContext, options: FetchEventsOptions) -> SourceQuery:
    if not options.city.strip():
        msg = "--city must not be blank"
        raise ConfigError(msg)
    if not 1 <= options.days <= MAX_DAYS:
        msg = f"--days must be between 1 and {MAX_DAYS}"
        raise ConfigError(msg)
    try:
        zone = ZoneInfo(options.home_tz)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        msg = f"unknown time zone {options.home_tz!r} (--home-tz or LAST_NEWSLETTER_HOME_TZ)"
        raise ConfigError(msg) from None
    today = ctx.now.astimezone(zone).date()
    return SourceQuery(
        city=options.city.strip(),
        region=options.region.strip(),
        country=options.country.strip() or "US",
        date_from=today,
        date_to=today + timedelta(days=options.days),
    )


def execute_fetch_events(ctx: FetchEventsContext, options: FetchEventsOptions) -> int:
    """Fetch, ingest, and print counts. Returns the exit code: 0 on success, 1 when the fetch
    failed (nothing was written; a rerun is safe)."""
    key = ctx.environ.get(KEY_VARIABLE, "").strip()
    if not key:
        msg = f"{KEY_VARIABLE} is not set (a free key: https://developer.ticketmaster.com)"
        raise ConfigError(msg)
    query = _query(ctx, options)
    source = TicketmasterEventSource(
        TicketmasterClient(key, transport=ctx.transport, sleep=ctx.sleep or time.sleep),
        TicketmasterConfig(dma_id=options.dma_id.strip()),
    )
    try:
        candidates = source.fetch(query, now=ctx.now)
    except SourceFetchError as error:
        ctx.err.write(f"last-newsletter: {error}; nothing was saved, a rerun is safe\n")
        return 1

    with ledger_session(ctx.data_dir, dry_run=options.dry_run) as session:
        session.sync_index()
        result = IngestSourceEvents(
            _Fetched(source.name, candidates),
            SourceIngestPorts(
                repository=session.ledger,
                ids=ctx.ids or Uuid4Ids(),
                similar_index=CoreSimilarIndex(session.index),
            ),
            home_tz=options.home_tz,
            policy=LINK_ONLY_POLICY,
        ).ingest(query, now=ctx.now)
    where = ", ".join(part for part in (query.city, query.region) if part)
    header = (
        f"{source.name}: {len(candidates)} event(s) for {where}, "
        f"{query.date_from.isoformat()} to {query.date_to.isoformat()} "
        f"({source.stats.requests} request(s))"
    )
    tally = (
        f"events: {result.created} created, {result.mentioned} new mentions, "
        f"{result.unchanged} unchanged, {result.possible_duplicates} possible duplicates"
    )
    lines = [*session.notes, header, *_skipped_lines(source.stats), tally]
    if result.rejected_total:
        reasons = ", ".join(f"{r.value} {n}" for r, n in sorted(result.rejected.items()))
        lines.append(f"rejected: {result.rejected_total} ({reasons})")
    ctx.out.write("\n".join(lines) + "\n")
    return 0


def _skipped_lines(stats: FetchStats) -> list[str]:
    lines: list[str] = []
    if stats.skipped:
        reasons = ", ".join(f"{reason} {n}" for reason, n in sorted(stats.skipped.items()))
        lines.append(f"skipped: {reasons}")
    if stats.outside_window:
        lines.append(f"outside the requested dates: {stats.outside_window}")
    if stats.truncated:
        lines.append(
            f"WARNING: {stats.truncated} match(es) beyond the API's 1,000-result cap were not "
            "fetched; narrow the search (--days, --city, --dma-id)"
        )
    return lines
