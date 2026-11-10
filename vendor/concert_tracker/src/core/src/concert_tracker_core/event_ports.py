"""Event-ledger ports (docs/design/event-ledger.md section 6). Core defines them; adapters
implement them. Nothing here may import an adapter.

Signatures other packages build against:

    IdGenerator.new_event_id() -> EventId
    Clock.now() -> datetime                                       # tz-aware
    EmbeddedEventReader.read(message) -> list[EventCandidate]
    EventExtractor.extract(messages, *, now, home_tz) -> list[EventCandidate]
    #   (may raise ExtractionFailedError)
    EventSource.fetch(window, *, now) -> SourceBatch              # (may raise SourceFetchError)
    EventRepository.get(event_id) -> Event | None
    EventRepository.find_candidates(query) -> list[Event]
    EventRepository.list_open() -> list[Event]
    EventRepository.upsert(event) -> None
    EventRepository.record_mention(event_id, mention) -> None
    SimilarEventIndex.index(event) -> None
    SimilarEventIndex.similar(candidate, *, limit) -> list[tuple[EventId, float]]
    DocumentStore.put(message) -> RawRef
    DocumentStore.get(ref) -> SourceDocument | None
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime

    from concert_tracker_core.documents import SourceDocument
    from concert_tracker_core.events import (
        Event,
        EventCandidate,
        EventDraft,
        EventId,
        Mention,
        RawRef,
    )


class ExtractionFailedError(Exception):
    """An `EventExtractor` could not produce a result for this batch (model error, refusal,
    timeout). It is the only exception `IngestEvents` absorbs; it counts the batch as failed and
    carries on. Re-ingesting later is safe because ingest is idempotent."""


class IdGenerator(Protocol):
    """Source of event ids. Core never calls `uuid4` itself (randomness is an effect)."""

    def new_event_id(self) -> EventId: ...


class Clock(Protocol):
    """The current time, tz-aware. Only `cli` implements this with the real clock; use cases
    take `now` as an argument instead of holding a clock."""

    def now(self) -> datetime: ...


class EmbeddedEventReader(Protocol):
    """Reads structured events already in a message (JSON-LD, Microdata, `.ics`). Cheap and
    deterministic, so it runs before the model. Returns candidates whose `message_id` is the
    message's own; `evidence` is a quoted snippet (it is not checked against the body)."""

    def read(self, message: SourceDocument) -> list[EventCandidate]: ...


class EventExtractor(Protocol):
    """Extracts candidates from message text, typically with a model. No tools, no network
    beyond the model call. Each candidate's `message_id` must name one of `messages`, and its
    `evidence` must be a quote from that message (ingest checks, and rejects what it cannot find).
    Raise `ExtractionFailedError` for a retryable failure of the whole batch."""

    def extract(
        self, messages: Sequence[SourceDocument], *, now: datetime, home_tz: str
    ) -> list[EventCandidate]: ...


class SourceFetchError(Exception):
    """An `EventSource` could not fetch (network, quota, rejected key, unusable response). Unlike
    an extraction failure it is not absorbed: nothing was ingested, so the caller reports it and a
    rerun is safe because ingest is idempotent. The message must never contain a credential."""


@dataclass(frozen=True, slots=True)
class SourceWindow:
    """The one thing every source is asked: events on these local dates (inclusive). Everything
    else a source needs (a city, a feed URL, a genre filter) is its own configuration."""

    date_from: date
    date_to: date


@dataclass(frozen=True, slots=True)
class SourceReport:
    """What a source did, in counts only, so a quiet run and a lossy run look different.

    `skipped` maps a short reason to how many events were left out (cancelled, no date yet);
    `truncated` counts matches the source reported but could not be fetched (a paging cap);
    `notes` carries lines the source requires us to show, such as an attribution.
    """

    requests: int = 0
    seen: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    outside_window: int = 0
    truncated: int = 0
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceBatch:
    candidates: list[EventCandidate]
    report: SourceReport = field(default_factory=SourceReport)


class EventSource(Protocol):
    """A structured source of events (a ticketing API, a venue calendar feed). Returns candidates
    that already carry their own identity: `uid` and `url` where the source has them, and a
    `message_id` of the form "<name>:<source id>" so a mention can name where it came from.

    `evidence` must be stable for unchanged facts and change when the title, date, time or venue
    change; that is what lets a rerun count as unchanged and a reschedule count as new.
    `sequence` is set so a later fetch of a changed event wins. A source performs the network
    calls; it raises `SourceFetchError` for any failure to fetch."""

    @property
    def name(self) -> str: ...

    def fetch(self, window: SourceWindow, *, now: datetime) -> SourceBatch: ...


@dataclass(frozen=True, slots=True)
class CandidateQuery:
    """Which stored events could be the same as a new draft.

    An event qualifies if its `uid` equals `uid`, or its `url` equals `url` (both only when not
    None), or its local date lies in `date_from..date_to` inclusive.
    """

    uid: str | None
    url: str | None
    date_from: date
    date_to: date


class EventRepository(Protocol):
    """Durable store of events and their mentions.

    Contract (the same test suite runs against every implementation):
    - `get` returns None for an unknown id.
    - `find_candidates` returns the union described on `CandidateQuery`, in any state that is
      open or recently closed; the ladder in core does the actual matching.
    - `list_open` returns events whose state is OPEN or SNOOZED, for seeding an index and for
      digests.
    - `upsert` inserts or replaces by `event.id`, storing mentions and `possible_duplicates`
      exactly as given.
    - `record_mention` appends one mention to a known event and sets
      `last_seen = max(last_seen, mention.seen_at)`; it raises `KeyError` for an unknown id.
    """

    def get(self, event_id: EventId) -> Event | None: ...

    def find_candidates(self, query: CandidateQuery) -> list[Event]: ...

    def list_open(self) -> list[Event]: ...

    def upsert(self, event: Event) -> None: ...

    def record_mention(self, event_id: EventId, mention: Mention) -> None: ...


class SimilarEventIndex(Protocol):
    """Fuzzy "which known events look like this one" lookup; the optional last rung of the
    identity ladder, consulted only when the deterministic rungs found nothing. Core ships a
    stdlib `difflib` implementation (`DifflibSimilarEventIndex`); a semantic index implements
    the same two methods.

    - `index(event)`: add or replace the entry for `event.id`. Idempotent. Core calls it when
      an event is created or its text changes. Text worth embedding: title, summary, entity
      names.
    - `similar(candidate, *, limit)`: up to `limit` known events most like `candidate`, as
      `(event_id, score)` with score in [0, 1], highest first. May return ids the repository no
      longer has (core skips them). It must not filter by date; core applies the date window
      and venue checks. Scores are compared to `IdentityPolicy` thresholds, so higher must mean
      more alike across calls.
    - When a caller supplies its own index it owns persistence and seeding. When none is
      supplied, `IngestEvents` uses the difflib default and seeds it from `list_open()` on
      every run.
    """

    def index(self, event: Event) -> None: ...

    def similar(self, candidate: EventDraft, *, limit: int) -> list[tuple[EventId, float]]: ...


class DocumentStore(Protocol):
    """Keeps the source message so a rule change can be re-run and every event traces to its
    document (design section 6). Lives in the runtime data dir; core never reads files itself.

    - `put(message)`: store and return a stable `RawRef`. Idempotent: putting the same
      `message_id` again returns the same ref (and may refresh the content).
    - `get(ref)`: the stored message, or None for an unknown ref.
    """

    def put(self, message: SourceDocument) -> RawRef: ...

    def get(self, ref: RawRef) -> SourceDocument | None: ...
