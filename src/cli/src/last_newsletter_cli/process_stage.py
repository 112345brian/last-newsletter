"""Stage 2 of the pipeline: raw store -> `IngestEvents`. Reads only the local raw store, so it
needs no network and no IMAP credentials, and it is safe to re-run on the same mail.

A raw ref is marked processed only after its batch ingested with no extraction failure. A failed
batch stays unmarked and is retried next run (ingest is idempotent, so a retry never duplicates).
The `IngestResult` of every batch is folded into the returned summary, never dropped.
"""

from __future__ import annotations

__arbor__ = {"ring": "cli"}

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from concert_tracker_core.use_cases import IngestResult

from last_newsletter_adapter_storage import to_document

if TYPE_CHECKING:
    from datetime import datetime

    from concert_tracker_core.use_cases import IngestEvents

    from last_newsletter_adapter_storage import ListableRawMessageStore, ProcessedMarkers

DEFAULT_BATCH_SIZE = 10


@dataclass(frozen=True, slots=True)
class Batching:
    """How the todo list is cut up. `max_failed` gives up after that many failed batches (an
    offline model fails every batch; waiting on each one would take hours)."""

    size: int = DEFAULT_BATCH_SIZE
    max_failed: int | None = None


@dataclass(slots=True)
class ProcessSummary:
    """Totals over every batch of one run. `result` is the merged `IngestResult`."""

    result: IngestResult = field(default_factory=IngestResult)
    seen: int = 0  # raw messages in the store
    already_processed: int = 0
    processed: int = 0  # messages ingested and marked this run
    retry_later: int = 0  # messages in batches that hit an extraction failure
    unreadable: int = 0  # refs the store listed but could not return
    gave_up: bool = False  # stopped early after repeated failed batches (e.g. model offline)

    def lines(self) -> list[str]:
        r = self.result
        counts = (
            f"raw messages: {self.seen} ({self.already_processed} already processed, "
            f"{self.processed} processed now, {self.retry_later} to retry, "
            f"{self.unreadable} unreadable)"
        )
        events = (
            f"events: {r.created} created, {r.mentioned} new mentions, "
            f"{r.unchanged} unchanged, {r.possible_duplicates} possible duplicates"
        )
        failures = f"extraction failures: {r.extraction_failures}; rejected: {r.rejected_total}"
        out = [counts, events, failures]
        if self.gave_up:
            out.append("stopped early: repeated extraction failures; the rest stays unprocessed")
        out.extend(f"  rejected {reason.value}: {n}" for reason, n in sorted(r.rejected.items()))
        return out


def _merge(a: IngestResult, b: IngestResult) -> IngestResult:
    rejected = dict(a.rejected)
    for reason, n in b.rejected.items():
        rejected[reason] = rejected.get(reason, 0) + n
    return IngestResult(
        created=a.created + b.created,
        mentioned=a.mentioned + b.mentioned,
        unchanged=a.unchanged + b.unchanged,
        possible_duplicates=a.possible_duplicates + b.possible_duplicates,
        extraction_failures=a.extraction_failures + b.extraction_failures,
        rejected=rejected,
        created_ids=(*a.created_ids, *b.created_ids),
    )


def process_raw(
    store: ListableRawMessageStore,
    markers: ProcessedMarkers,
    ingest: IngestEvents,
    *,
    now: datetime,
    batching: Batching | None = None,
) -> ProcessSummary:
    batching = batching or Batching()
    batch_size = batching.size
    max_failed_batches = batching.max_failed
    if batch_size < 1:
        msg = "batch size must be at least 1"
        raise ValueError(msg)
    summary = ProcessSummary()
    done = markers.processed()
    refs = sorted(store.list())
    summary.seen = len(refs)
    todo = [ref for ref in refs if ref not in done]
    summary.already_processed = len(refs) - len(todo)
    failed_batches = 0
    for start in range(0, len(todo), batch_size):
        batch_refs = todo[start : start + batch_size]
        loaded = [(ref, store.get(ref)) for ref in batch_refs]
        pairs = [(ref, m) for ref, m in loaded if m is not None]
        summary.unreadable += len(loaded) - len(pairs)
        if not pairs:
            continue
        result = ingest.ingest([to_document(m) for _, m in pairs], now=now)
        summary.result = _merge(summary.result, result)
        if result.extraction_failures:
            summary.retry_later += len(pairs)
            failed_batches += 1
            if max_failed_batches is not None and failed_batches >= max_failed_batches:
                # An offline model fails every batch; stop instead of waiting on each one.
                summary.gave_up = True
                summary.retry_later += len(todo) - start - len(batch_refs)
                break
            continue
        markers.mark([ref for ref, _ in pairs])
        summary.processed += len(pairs)
    return summary
