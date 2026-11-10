"""Application rule: a structured source's candidates -> the same validate -> identity ladder ->
create-or-cite path as email (`IngestEvents`). No matching logic lives here.

Each source candidate is wrapped in a synthetic message (id "<source>:<id>", sender and label the
source's name, body the candidate's evidence) so mentions, idempotence and provenance work exactly
as for mail. The candidates are handed to `IngestEvents` through its embedded-reader port, which
is the path for already-structured data: the evidence is not checked against a body.

Fetching is separate from ingesting on purpose: a caller can do the slow network part first and
take the ledger lock only for the quick write (`fetch_and_ingest` does both for callers that
don't care).
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass
from typing import TYPE_CHECKING

from concert_tracker_core.documents import SourceDocument
from concert_tracker_core.use_cases.ingest_events import IngestEvents, IngestPorts, IngestResult

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from concert_tracker_core.event_identity import IdentityPolicy
    from concert_tracker_core.event_ports import (
        EventRepository,
        EventSource,
        IdGenerator,
        SimilarEventIndex,
        SourceBatch,
        SourceWindow,
    )
    from concert_tracker_core.events import EventCandidate


@dataclass(frozen=True, slots=True)
class SourceIngestPorts:
    """The collaborators `IngestSourceEvents` needs besides the source itself."""

    repository: EventRepository
    ids: IdGenerator
    similar_index: SimilarEventIndex | None = None


class _FetchedReader:
    """`EmbeddedEventReader` over candidates already fetched for this run."""

    def __init__(self, by_message: dict[str, list[EventCandidate]]) -> None:
        self._by_message = by_message

    def read(self, message: SourceDocument) -> list[EventCandidate]:
        return list(self._by_message.get(message.message_id, []))


class _NoExtraction:
    """Every source message carries its candidates, so the model path is never needed."""

    def extract(
        self, messages: Sequence[SourceDocument], *, now: datetime, home_tz: str
    ) -> list[EventCandidate]:
        _ = (messages, now, home_tz)
        return []


class IngestSourceEvents:
    def __init__(
        self,
        source_name: str,
        ports: SourceIngestPorts,
        *,
        home_tz: str,
        policy: IdentityPolicy | None = None,
    ) -> None:
        self._name = source_name
        self._ports = ports
        self._home_tz = home_tz
        self._policy = policy

    def ingest_batch(self, batch: SourceBatch, *, now: datetime) -> IngestResult:
        """Ingest candidates a source already fetched."""
        by_message: dict[str, list[EventCandidate]] = {}
        for candidate in batch.candidates:
            by_message.setdefault(candidate.message_id, []).append(candidate)
        messages = [
            SourceDocument(
                message_id=message_id,
                sender=self._name,
                subject=group[0].title or "",
                received_at=now,
                body_text=group[0].evidence,
                source_label=self._name,
            )
            for message_id, group in by_message.items()
        ]
        ingest = IngestEvents(
            IngestPorts(
                repository=self._ports.repository,
                reader=_FetchedReader(by_message),
                extractor=_NoExtraction(),
                ids=self._ports.ids,
                similar_index=self._ports.similar_index,
            ),
            home_tz=self._home_tz,
            policy=self._policy,
        )
        return ingest.ingest(messages, now=now)

    def fetch_and_ingest(
        self, source: EventSource, window: SourceWindow, *, now: datetime
    ) -> IngestResult:
        """Fetch then ingest. `SourceFetchError` propagates: nothing was ingested, rerun is safe."""
        return self.ingest_batch(source.fetch(window, now=now), now=now)
