"""Application rule: documents -> embedded reader, then extractor -> validate -> identity ladder
-> create an event or record a mention -> `IngestResult`.

A document the embedded reader found events in is not sent to the extractor (saves model cost).
Ingest is idempotent: a mention is keyed by (document id, evidence), so re-ingesting the same
document changes nothing. Only `ExtractionFailedError` is absorbed; any other port failure
propagates, and a rerun picks up where it stopped.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import TYPE_CHECKING

from concert_tracker_core.event_identity import Decision, IdentityPolicy, identify
from concert_tracker_core.event_ports import CandidateQuery, ExtractionFailedError
from concert_tracker_core.event_rules import RejectReason, validate_candidate
from concert_tracker_core.event_similarity import DifflibSimilarEventIndex
from concert_tracker_core.events import Event, MatchRule, Mention, local_date, require_aware

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from concert_tracker_core.documents import SourceDocument
    from concert_tracker_core.event_ports import (
        DocumentStore,
        EmbeddedEventReader,
        EventExtractor,
        EventRepository,
        IdGenerator,
        SimilarEventIndex,
    )
    from concert_tracker_core.events import EventCandidate, EventDraft, EventId, RawRef

_SIMILAR_LIMIT = 5
_WINDOW = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What one ingest run did. Callers must read it: a run that rejected everything or lost an
    extraction batch looks identical to a quiet one unless someone looks at the counts."""

    created: int = 0
    mentioned: int = 0
    unchanged: int = 0
    possible_duplicates: int = 0
    extraction_failures: int = 0
    rejected: dict[RejectReason, int] = field(default_factory=dict)
    created_ids: tuple[EventId, ...] = ()

    @property
    def rejected_total(self) -> int:
        return sum(self.rejected.values())


class _Tally:
    def __init__(self) -> None:
        self.created_ids: list[EventId] = []
        self.mentioned = 0
        self.unchanged = 0
        self.possible_duplicates = 0
        self.extraction_failures = 0
        self.rejected: dict[RejectReason, int] = {}

    def reject(self, reason: RejectReason) -> None:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1

    def result(self) -> IngestResult:
        return IngestResult(
            created=len(self.created_ids),
            mentioned=self.mentioned,
            unchanged=self.unchanged,
            possible_duplicates=self.possible_duplicates,
            extraction_failures=self.extraction_failures,
            rejected=dict(self.rejected),
            created_ids=tuple(self.created_ids),
        )


@dataclass(slots=True)
class _Run:
    now: datetime
    index: SimilarEventIndex
    tally: _Tally
    raw_refs: dict[str, RawRef] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IngestPorts:
    """The collaborators `IngestEvents` needs. `similar_index=None` means the difflib default,
    seeded from `repository.list_open()` on every run."""

    repository: EventRepository
    reader: EmbeddedEventReader
    extractor: EventExtractor
    ids: IdGenerator
    similar_index: SimilarEventIndex | None = None
    raw_store: DocumentStore | None = None


class IngestEvents:
    def __init__(
        self, ports: IngestPorts, *, home_tz: str, policy: IdentityPolicy | None = None
    ) -> None:
        self._repository = ports.repository
        self._reader = ports.reader
        self._extractor = ports.extractor
        self._ids = ports.ids
        self._index = ports.similar_index
        self._raw_store = ports.raw_store
        self._home_tz = home_tz
        self._policy = policy or IdentityPolicy()

    def ingest(self, messages: Sequence[SourceDocument], *, now: datetime) -> IngestResult:
        require_aware(now, "now")
        tally = _Tally()
        index = self._index
        if index is None:  # default index lives for one run, so seed it from the ledger
            index = DifflibSimilarEventIndex()
            for event in self._repository.list_open():
                index.index(event)
        run = _Run(now=now, index=index, tally=tally)

        by_id: dict[str, SourceDocument] = {}
        for message in messages:
            if message.received_at.tzinfo is None or message.received_at.utcoffset() is None:
                tally.reject(RejectReason.NAIVE_RECEIVED_AT)
            else:
                by_id.setdefault(message.message_id, message)

        needs_extraction: dict[str, SourceDocument] = {}
        for message in by_id.values():
            if self._raw_store is not None:
                run.raw_refs[message.message_id] = self._raw_store.put(message)
            candidates = self._reader.read(message)
            for candidate in candidates:
                self._process(candidate, {message.message_id: message}, run, check_evidence=False)
            if not candidates:
                needs_extraction[message.message_id] = message
        self._extract(needs_extraction, run)
        return tally.result()

    def _extract(self, messages: dict[str, SourceDocument], run: _Run) -> None:
        if not messages:
            return
        try:
            extracted = self._extractor.extract(
                list(messages.values()), now=run.now, home_tz=self._home_tz
            )
        except ExtractionFailedError:
            run.tally.extraction_failures += len(messages)
            return
        for candidate in extracted:
            self._process(candidate, messages, run, check_evidence=True)

    def _process(
        self,
        candidate: EventCandidate,
        known: dict[str, SourceDocument],
        run: _Run,
        *,
        check_evidence: bool,
    ) -> None:
        message = known.get(candidate.message_id)
        if message is None:
            run.tally.reject(RejectReason.UNKNOWN_MESSAGE)
            return
        draft = validate_candidate(
            candidate,
            message_body=f"{message.subject}\n{message.body_text}",
            now=run.now,
            home_tz=self._home_tz,
            check_evidence=check_evidence,
        )
        if isinstance(draft, RejectReason):
            run.tally.reject(draft)
            return
        day = local_date(draft.when)
        pool = self._repository.find_candidates(
            CandidateQuery(
                uid=draft.uid, url=draft.url, date_from=day - _WINDOW, date_to=day + _WINDOW
            )
        )
        decision = identify(
            draft,
            pool,
            similar=lambda: self._similar_hits(draft, run.index),
            policy=self._policy,
        )
        if decision.event is None:
            self._create(draft, decision, message, run)
        else:
            self._cite(draft, decision, message, run)

    def _similar_hits(
        self, draft: EventDraft, index: SimilarEventIndex
    ) -> list[tuple[Event, float]]:
        hits: list[tuple[Event, float]] = []
        for event_id, score in index.similar(draft, limit=_SIMILAR_LIMIT):
            event = self._repository.get(event_id)
            if event is not None:
                hits.append((event, score))
        return hits

    def _create(
        self,
        draft: EventDraft,
        decision: Decision,
        message: SourceDocument,
        run: _Run,
    ) -> None:
        event_id = self._ids.new_event_id()
        mention = _mention(
            draft, message, MatchRule.NEW, event_id, run.raw_refs.get(message.message_id)
        )
        event = Event(
            id=event_id,
            kind=draft.kind,
            title=draft.title,
            summary=draft.summary,
            when=draft.when,
            entities=draft.entities,
            mentions=(mention,),
            first_seen=mention.seen_at,
            last_seen=mention.seen_at,
            possible_duplicates=decision.possible_duplicates,
            uid=draft.uid,
            sequence=draft.sequence,
            url=draft.url,
            city=draft.city,
            tags=draft.tags,
            price=draft.price,
            age=draft.age,
            night_of=draft.night_of,
            showtimes=draft.showtimes,
        )
        self._repository.upsert(event)
        run.index.index(event)
        for other_id in decision.possible_duplicates:  # links are symmetric
            other = self._repository.get(other_id)
            if other is not None and event_id not in other.possible_duplicates:
                self._repository.upsert(
                    replace(other, possible_duplicates=(*other.possible_duplicates, event_id))
                )
        run.tally.created_ids.append(event_id)
        if decision.possible_duplicates:
            run.tally.possible_duplicates += 1

    def _cite(
        self,
        draft: EventDraft,
        decision: Decision,
        message: SourceDocument,
        run: _Run,
    ) -> None:
        existing = decision.event
        if existing is None:  # pragma: no cover - guarded by the caller
            return
        if any(
            m.message_id == message.message_id and m.evidence == draft.evidence
            for m in existing.mentions
        ):
            run.tally.unchanged += 1
            return
        mention = _mention(
            draft, message, decision.rule, existing.id, run.raw_refs.get(message.message_id)
        )
        if decision.rule is MatchRule.UID and draft.sequence > existing.sequence:
            # A higher SEQUENCE updates the facts; owner state and history are kept.
            updated = replace(
                existing,
                kind=draft.kind,
                title=draft.title,
                summary=draft.summary,
                when=draft.when,
                entities=draft.entities,
                url=draft.url or existing.url,
                city=draft.city,
                tags=draft.tags,
                price=draft.price,
                age=draft.age,
                night_of=draft.night_of,
                showtimes=draft.showtimes,
                sequence=draft.sequence,
                mentions=(*existing.mentions, mention),
                last_seen=max(existing.last_seen, mention.seen_at),
            )
            self._repository.upsert(updated)
            run.index.index(updated)
        else:
            self._repository.record_mention(existing.id, mention)
        run.tally.mentioned += 1


def _mention(
    draft: EventDraft,
    message: SourceDocument,
    rule: MatchRule,
    event_id: EventId,
    raw_ref: RawRef | None,
) -> Mention:
    return Mention(
        message_id=message.message_id,
        seen_at=message.received_at,
        source=message.source_label or message.sender,
        evidence=draft.evidence,
        match_rule=rule,
        cited_event_id=event_id,
        raw_date_text=draft.raw_date_text,
        raw_ref=raw_ref,
    )
