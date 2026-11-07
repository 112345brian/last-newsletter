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

from last_newsletter_core.use_cases import IngestResult

if TYPE_CHECKING:
    from datetime import datetime

    from last_newsletter_adapter_storage import ListableRawMessageStore, ProcessedMarkers
    from last_newsletter_core.use_cases import IngestEvents

DEFAULT_BATCH_SIZE = 10


@dataclass(slots=True)
class ProcessSummary:
    """Totals over every batch of one run. `result` is the merged `IngestResult`."""

    result: IngestResult = field(default_factory=IngestResult)
    seen: int = 0  # raw messages in the store
    already_processed: int = 0
    processed: int = 0  # messages ingested and marked this run
    retry_later: int = 0  # messages in batches that hit an extraction failure
    unreadable: int = 0  # refs the store listed but could not return

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
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> ProcessSummary:
    if batch_size < 1:
        msg = "batch_size must be at least 1"
        raise ValueError(msg)
    summary = ProcessSummary()
    done = markers.processed()
    refs = sorted(store.list())
    summary.seen = len(refs)
    todo = [ref for ref in refs if ref not in done]
    summary.already_processed = len(refs) - len(todo)
    for start in range(0, len(todo), batch_size):
        batch_refs = todo[start : start + batch_size]
        loaded = [(ref, store.get(ref)) for ref in batch_refs]
        pairs = [(ref, m) for ref, m in loaded if m is not None]
        summary.unreadable += len(loaded) - len(pairs)
        if not pairs:
            continue
        result = ingest.ingest([m for _, m in pairs], now=now)
        summary.result = _merge(summary.result, result)
        if result.extraction_failures:
            summary.retry_later += len(pairs)
            continue
        markers.mark([ref for ref, _ in pairs])
        summary.processed += len(pairs)
    return summary
