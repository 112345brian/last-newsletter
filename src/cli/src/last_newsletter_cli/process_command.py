"""The `process` command: builds the real adapters and runs stage 2.

Everything ambient (data directory, environment, clock, HTTP transport, id source) is passed in
by `main`, so tests drive the exact same code with a temp dir, a fixed clock and a fake Ollama.
Nothing below this module reads the environment or the clock.

Layout under `<data_dir>/events/`:
    ledger.sqlite    the event ledger (source of truth; SQLite `EventRepository`)
    similar.sqlite   the semantic index (a cache; rebuilt from the ledger when out of sync)
    processed.json   which raw messages were fully ingested
    events.json      the old JSON ledger; imported once, then renamed to events.json.imported
"""

from __future__ import annotations

__arbor__ = {"ring": "cli"}

import shutil
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from last_newsletter_adapter_events import LocalLlmEventExtractor, OllamaClient, OllamaConfig
from last_newsletter_adapter_ledger import SqliteEventRepository, ledger_write_lock
from last_newsletter_adapter_semantic import HashedNgramIndex
from last_newsletter_adapter_storage import FileRawMessageStore, ProcessedMarkers
from last_newsletter_adapter_summarizer.dated_line_extractor import (
    DatedLineExtractor,
    NoEmbeddedEvents,
)
from last_newsletter_cli.ledger_import import import_json_ledger
from last_newsletter_cli.process_stage import (
    DEFAULT_BATCH_SIZE,
    Batching,
    ProcessSummary,
    process_raw,
)
from last_newsletter_cli.similarity import LINK_ONLY_POLICY, CoreSimilarIndex, sync_index
from last_newsletter_core.events import EventId
from last_newsletter_core.use_cases import IngestEvents, IngestPorts

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import datetime
    from typing import TextIO

    from last_newsletter_core.event_ports import EventExtractor
    from llmhost.transport import Transport

DEFAULT_OLLAMA_MODEL = "gpt-oss:120b"
EXTRACTOR_CHOICES = ("dated-lines", "local-llm")
# Stop after this many consecutive-looking failed batches: an offline model fails every batch.
_MAX_FAILED_BATCHES = 2
LEDGER_NAME = "ledger.sqlite"
INDEX_NAME = "similar.sqlite"


class ConfigError(Exception):
    """A setting is missing or invalid. Its message names the variable to fix."""


class IdGenerator(Protocol):
    def new_event_id(self) -> EventId: ...


class Uuid4Ids:
    """`IdGenerator`: random UUIDs (randomness is an effect, so it lives outside core)."""

    def new_event_id(self) -> EventId:
        return EventId(uuid4())


@dataclass(frozen=True, slots=True)
class ProcessContext:
    """Everything ambient, handed in by `main` (or a test): where, when, which environment and
    which streams. `ids`, `transport` and `sleep` default to the real ones."""

    data_dir: Path
    now: datetime
    environ: Mapping[str, str]
    out: TextIO
    err: TextIO
    ids: IdGenerator | None = None
    transport: Transport | None = None
    sleep: Callable[[float], None] | None = None


@dataclass(frozen=True, slots=True)
class ProcessOptions:
    extractor: str = "dated-lines"
    home_tz: str = "UTC"
    batch_size: int = DEFAULT_BATCH_SIZE
    dry_run: bool = False
    reprocess: bool = False  # back up the ledger, index and markers, then start from scratch


def ollama_config(environ: Mapping[str, str]) -> OllamaConfig:
    """Model and URL from `LAST_NEWSLETTER_OLLAMA_MODEL` / `LAST_NEWSLETTER_OLLAMA_URL`.

    No key, token or cloud endpoint is read: this talks to a model on this machine.
    """
    model = environ.get("LAST_NEWSLETTER_OLLAMA_MODEL", "").strip() or DEFAULT_OLLAMA_MODEL
    url = environ.get("LAST_NEWSLETTER_OLLAMA_URL", "").strip() or None  # None: llmhost's default
    # gpt-oss takes an effort level; the qwen3 family needs thinking switched off.
    think: bool | str | None = None
    if model.startswith("gpt-oss"):
        think = "low"
    elif model.startswith("qwen3"):
        think = False
    return OllamaConfig(model=model, base_url=url, think=think)


def _extractor(
    name: str,
    environ: Mapping[str, str],
    transport: Transport | None,
    sleep: Callable[[float], None] | None,
) -> EventExtractor:
    if name == "dated-lines":
        return DatedLineExtractor()
    if name == "local-llm":
        config = ollama_config(environ)
        client = (
            OllamaClient(config, transport=transport, sleep=sleep)
            if sleep is not None
            else OllamaClient(config, transport=transport)
        )
        return LocalLlmEventExtractor(client)  # cloud escalation stays off: no escalator given
    msg = f"unknown extractor {name!r}"
    raise ConfigError(msg)


def copy_for_dry_run(events_dir: Path, scratch: Path) -> Path:
    """A throwaway copy of the state `process` writes, so a dry run can change nothing real.

    The index is not copied at all, so it is rebuilt from the copied ledger.
    """
    target = scratch / "events"
    if events_dir.is_dir():
        shutil.copytree(
            events_dir, target, ignore=shutil.ignore_patterns(f"{LEDGER_NAME}*", f"{INDEX_NAME}*")
        )
    else:
        target.mkdir(parents=True)
    ledger = events_dir / LEDGER_NAME
    if ledger.exists():
        # Copy the database with its WAL under the write lock (so no run is mid-write), then
        # let SQLite recover the copy. Opening the original, even read-only, can leave -shm/-wal
        # files behind, and a dry run must leave the real directory exactly as it found it.
        with ledger_write_lock(ledger, timeout_s=5.0):
            for suffix in ("", "-wal", "-shm"):
                part = events_dir / f"{LEDGER_NAME}{suffix}"
                if part.exists():
                    shutil.copy2(part, target / part.name)
    return target


def _reset_state(events_dir: Path, *, now: datetime, keep_backup: bool) -> Path | None:
    """Clear the ledger, the index and the processed markers so the raw store is processed anew.

    With `keep_backup` the files are moved (never deleted) into `backup-<timestamp>/` beside them
    and that folder is returned; a dry run works on a scratch copy and just drops the files.
    """
    names = sorted(
        p.name
        for pattern in (f"{LEDGER_NAME}*", f"{INDEX_NAME}*", "processed.json")
        for p in events_dir.glob(pattern)
        if not p.name.endswith(".lock")
    )
    backup = events_dir / f"backup-{now:%Y%m%dT%H%M%S}" if keep_backup and names else None
    with ledger_write_lock(events_dir / LEDGER_NAME, timeout_s=5.0):
        if backup is not None:
            backup.mkdir()
        for name in names:
            if backup is not None:
                shutil.move(events_dir / name, backup / name)
            else:
                (events_dir / name).unlink()
    return backup


def _describe_stats(extractor: EventExtractor) -> list[str]:
    if not isinstance(extractor, LocalLlmEventExtractor):
        return []
    s = extractor.stats
    line = (
        f"local model: {s.messages} messages, {s.prefiltered_out} skipped as dateless, "
        f"{s.model_calls} model calls, {s.schema_failures} unusable answers"
    )
    return [line]


def execute_process(ctx: ProcessContext, options: ProcessOptions) -> int:
    """Run stage 2 and print its summary. Returns the process exit code.

    0: every batch was ingested. 1: some messages stayed unprocessed (model offline or failing);
    they are retried by the next run. A dry run copies the state first and writes nothing real.
    """
    raw_dir = ctx.data_dir / "raw"
    notes: list[str] = []
    with ExitStack() as stack:
        if options.dry_run:
            scratch = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="ln-dry-")))
            events_dir = copy_for_dry_run(ctx.data_dir / "events", scratch)
            notes.append("DRY RUN: nothing below was saved")
        else:
            events_dir = ctx.data_dir / "events"
            events_dir.mkdir(parents=True, exist_ok=True)
        if options.reprocess:
            backup = _reset_state(events_dir, now=ctx.now, keep_backup=not options.dry_run)
            if backup is not None:
                notes.append(f"backed up the previous ledger to {backup}; processing from scratch")
            else:
                notes.append("--reprocess: started from an empty ledger")
        extractor = _extractor(options.extractor, ctx.environ, ctx.transport, ctx.sleep)
        ledger = stack.enter_context(SqliteEventRepository(events_dir / LEDGER_NAME))
        index = HashedNgramIndex(events_dir / INDEX_NAME)
        stack.callback(index.close)
        # One run at a time over the ledger, the index and the processed markers.
        with ledger_write_lock(events_dir / LEDGER_NAME, timeout_s=5.0):
            imported = import_json_ledger(events_dir / "events.json", ledger)
            if imported:
                notes.append(f"imported {imported} event(s) from the old JSON ledger")
            if sync_index(index, ledger.list_all()):
                notes.append("rebuilt the similarity index from the ledger")
            ingest = IngestEvents(
                IngestPorts(
                    repository=ledger,
                    reader=NoEmbeddedEvents(),
                    extractor=extractor,
                    ids=ctx.ids or Uuid4Ids(),
                    raw_store=FileRawMessageStore(raw_dir),
                    similar_index=CoreSimilarIndex(index),
                ),
                home_tz=options.home_tz,
                policy=LINK_ONLY_POLICY,
            )
            local = options.extractor == "local-llm"
            summary = process_raw(
                FileRawMessageStore(raw_dir),
                ProcessedMarkers(events_dir / "processed.json"),
                ingest,
                now=ctx.now,
                batching=Batching(options.batch_size, _MAX_FAILED_BATCHES if local else None),
            )
    return _report(summary, notes, options, extractor, ctx)


def _report(
    summary: ProcessSummary,
    notes: list[str],
    options: ProcessOptions,
    extractor: EventExtractor,
    ctx: ProcessContext,
) -> int:
    lines = [*notes, *summary.lines(), *_describe_stats(extractor)]
    ctx.out.write("\n".join(lines) + "\n")
    if summary.result.extraction_failures == 0:
        return 0
    n = summary.retry_later
    if options.extractor == "local-llm":
        config = ollama_config(ctx.environ)
        ctx.err.write(
            f"last-newsletter: the local model failed on {n} message(s); they stay unprocessed "
            f"and will be retried on the next run. Is Ollama running at {config.base_url} with "
            f"model {config.model!r} pulled (`ollama serve`, `ollama pull {config.model}`)?\n"
        )
    else:
        ctx.err.write(
            f"last-newsletter: extraction failed for {n} message(s); they will be retried\n"
        )
    return 1
