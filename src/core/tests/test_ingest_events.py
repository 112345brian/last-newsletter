from dataclasses import replace
from datetime import UTC, date, datetime, time
from uuid import UUID

import pytest
from event_fakes import (
    InMemoryEventRepository,
    ScriptedExtractor,
    ScriptedReader,
    SequentialIds,
)

from last_newsletter_core.entities import EmailMessage
from last_newsletter_core.event_identity import IdentityPolicy
from last_newsletter_core.event_ports import SimilarEventIndex
from last_newsletter_core.event_rules import RejectReason
from last_newsletter_core.event_similarity import DifflibSimilarEventIndex
from last_newsletter_core.events import (
    AllDay,
    EntityRef,
    EntityRole,
    Event,
    EventCandidate,
    EventDraft,
    EventId,
    ItemState,
    MatchRule,
    PartialWhen,
    RawRef,
    local_date,
)
from last_newsletter_core.raw_store import InMemoryRawMessageStore
from last_newsletter_core.use_cases import IngestEvents, IngestPorts, IngestResult

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_TZ = "America/New_York"


def _message(
    message_id: str = "m1", body: str = "Band at Venue, Dec 12. Doors 8pm."
) -> EmailMessage:
    return EmailMessage(
        message_id=message_id,
        sender="promo@example.com",
        subject="Shows",
        received_at=datetime(2026, 11, 5, tzinfo=UTC),
        body_text=body,
        source_label="promoter",
    )


_BASE_CANDIDATE = EventCandidate(
    message_id="m1",
    title="Band at Venue",
    when=PartialWhen(year=2026, month=12, day=12, raw_text="Dec 12"),
    evidence="Band at Venue, Dec 12",
    entities=(EntityRef(name="The Venue", role=EntityRole.VENUE),),
)


def _candidate(message_id: str = "m1", **overrides: object) -> EventCandidate:
    return replace(_BASE_CANDIDATE, message_id=message_id, **overrides)


def _use_case(
    *,
    repo: InMemoryEventRepository | None = None,
    reader: ScriptedReader | None = None,
    extractor: ScriptedExtractor | None = None,
    similar_index: SimilarEventIndex | None = None,
    policy: IdentityPolicy | None = None,
) -> tuple[IngestEvents, InMemoryEventRepository]:
    repo = repo or InMemoryEventRepository()
    ports = IngestPorts(
        repository=repo,
        reader=reader or ScriptedReader(),
        extractor=extractor or ScriptedExtractor([]),
        ids=SequentialIds(start=len(repo.events) + 1),
        similar_index=similar_index,
    )
    return IngestEvents(ports, home_tz=_TZ, policy=policy), repo


def test_empty_batch_does_nothing_and_skips_the_model() -> None:
    extractor = ScriptedExtractor([])
    use_case, repo = _use_case(extractor=extractor)
    assert use_case.ingest([], now=_NOW) == IngestResult()
    assert extractor.calls == []
    assert repo.events == {}


def test_extracted_event_is_created_with_a_new_mention() -> None:
    use_case, repo = _use_case(extractor=ScriptedExtractor([_candidate()]))
    result = use_case.ingest([_message()], now=_NOW)
    assert (result.created, result.mentioned, result.rejected_total) == (1, 0, 0)
    (event,) = repo.events.values()
    assert event.id == EventId(UUID(int=1))
    assert event.id in result.created_ids
    assert event.when == AllDay(date(2026, 12, 12))
    assert event.state is ItemState.OPEN
    (mention,) = event.mentions
    assert (mention.match_rule, mention.cited_event_id) == (MatchRule.NEW, event.id)
    assert mention.source == "promoter"


def test_embedded_reader_runs_first_and_spares_the_model() -> None:
    reader = ScriptedReader({"m1": [_candidate(evidence="structured")]})
    extractor = ScriptedExtractor([_candidate("m2")])
    use_case, repo = _use_case(reader=reader, extractor=extractor)
    result = use_case.ingest([_message("m1"), _message("m2")], now=_NOW)
    assert extractor.calls == [["m2"]]
    assert result.created == 1  # m1 embedded; m2 then cites it
    assert len(repo.events) == 1  # same event: the second becomes a citation
    assert result.mentioned == 1


def test_later_email_about_the_same_event_is_a_citation_not_a_row() -> None:
    first, repo = _use_case(extractor=ScriptedExtractor([_candidate("m1")]))
    assert first.ingest([_message("m1")], now=_NOW).created == 1
    second, _ = _use_case(
        repo=repo,
        extractor=ScriptedExtractor([_candidate("m2", title="BAND at venue")]),
    )
    result = second.ingest([_message("m2", "BAND at venue... Band at Venue, Dec 12")], now=_NOW)
    assert (result.created, result.mentioned) == (0, 1)
    (event,) = repo.events.values()
    assert [m.message_id for m in event.mentions] == ["m1", "m2"]
    assert event.mentions[1].match_rule is MatchRule.TITLE_DATE_VENUE
    assert event.mentions[1].cited_event_id == event.id


def test_reingesting_the_same_email_is_idempotent() -> None:
    use_case, repo = _use_case(extractor=ScriptedExtractor([_candidate()]))
    assert use_case.ingest([_message()], now=_NOW).created == 1
    snapshot = dict(repo.events)
    again = use_case.ingest([_message()], now=_NOW)
    assert (again.created, again.mentioned, again.unchanged) == (0, 0, 1)
    assert repo.events == snapshot


def test_owner_state_survives_reextraction_and_sequence_update_changes_facts() -> None:
    use_case, repo = _use_case(
        extractor=ScriptedExtractor([_candidate("m1", uid="u1", sequence=1)])
    )
    assert use_case.ingest([_message("m1")], now=_NOW).created == 1
    (event,) = repo.events.values()
    repo.events[event.id] = replace(event, state=ItemState.DISMISSED)

    newer = _candidate(
        "m2",
        uid="u1",
        sequence=2,
        title="Band at Venue (moved)",
        when=PartialWhen(year=2026, month=12, day=19),
        evidence="moved to Dec 19",
    )
    older = _candidate("m3", uid="u1", sequence=0, title="Stale", evidence="stale mail")
    for candidate, body in ((newer, "moved to Dec 19"), (older, "stale mail")):
        step, _ = _use_case(repo=repo, extractor=ScriptedExtractor([candidate]))
        assert step.ingest([_message(candidate.message_id, body)], now=_NOW).rejected_total == 0
    (event,) = repo.events.values()
    assert event.state is ItemState.DISMISSED
    assert event.title == "Band at Venue (moved)"
    assert event.when == AllDay(date(2026, 12, 19))
    assert event.sequence == 2
    assert [m.match_rule for m in event.mentions] == [MatchRule.NEW, MatchRule.UID, MatchRule.UID]
    assert event.first_seen == datetime(2026, 11, 5, tzinfo=UTC)


def test_ambiguous_match_stays_separate_and_links_both_ways() -> None:
    use_case, repo = _use_case(extractor=ScriptedExtractor([_candidate(entities=())]))
    assert use_case.ingest([_message()], now=_NOW).created == 1
    venue_known = _use_case(repo=repo, extractor=ScriptedExtractor([_candidate("m2")]))[0]
    result = venue_known.ingest([_message("m2")], now=_NOW)
    # Same title and date, but one mention has no venue: not certain, so keep both.
    assert (result.created, result.mentioned, result.possible_duplicates) == (1, 0, 1)
    first, second = repo.events.values()
    assert second.possible_duplicates == (first.id,)
    assert first.possible_duplicates == (second.id,)


def test_rejections_are_counted_by_reason() -> None:
    bad = [
        _candidate(title="   "),
        _candidate(title="Ba\x00nd"),
        _candidate(when=PartialWhen(year=2026, month=1, day=1)),
        _candidate(evidence="invented line"),
        _candidate("ghost"),
        _candidate(when=None),
    ]
    use_case, repo = _use_case(extractor=ScriptedExtractor([*bad, _candidate()]))
    result = use_case.ingest([_message()], now=_NOW)
    assert result.created == 1
    assert result.rejected == {
        RejectReason.BLANK_TITLE: 1,
        RejectReason.CONTROL_CHARACTERS: 1,
        RejectReason.PAST_DATE: 1,
        RejectReason.EVIDENCE_NOT_IN_MESSAGE: 1,
        RejectReason.UNKNOWN_MESSAGE: 1,
        RejectReason.MISSING_DATE: 1,
    }
    assert len(repo.events) == 1


def test_partial_candidate_is_rejected_not_crashed() -> None:
    use_case, repo = _use_case(extractor=ScriptedExtractor([EventCandidate(message_id="m1")]))
    result = use_case.ingest([_message()], now=_NOW)
    assert result.rejected == {RejectReason.BLANK_TITLE: 1}
    assert repo.events == {}


def test_naive_inputs_are_refused() -> None:
    use_case, _ = _use_case()
    with pytest.raises(ValueError, match="timezone"):
        _ = use_case.ingest([], now=datetime(2026, 11, 6, tzinfo=UTC).replace(tzinfo=None))
    naive = replace(_message(), received_at=datetime(2026, 11, 5, tzinfo=UTC).replace(tzinfo=None))
    result = use_case.ingest([naive], now=_NOW)
    assert result.rejected == {RejectReason.NAIVE_RECEIVED_AT: 1}


def test_extractor_failure_is_counted_and_a_retry_succeeds_without_duplicates() -> None:
    reader = ScriptedReader({"m1": [_candidate("m1", evidence="structured")]})
    extractor = ScriptedExtractor([_candidate("m2")], fail_times=1)
    use_case, repo = _use_case(reader=reader, extractor=extractor)
    messages = [_message("m1"), _message("m2")]

    first = use_case.ingest(messages, now=_NOW)
    assert (first.extraction_failures, first.created) == (1, 1)  # embedded result kept

    second = use_case.ingest(messages, now=_NOW)
    assert second.extraction_failures == 0
    assert second.mentioned == 1  # m2 now cites the event m1 created
    assert second.unchanged == 1  # m1's own mention is already recorded
    assert len(repo.events) == 1


def test_repository_failure_propagates_and_a_rerun_completes_without_duplicates() -> None:
    other = _candidate(
        "m2",
        title="Other Show",
        evidence="Other Show, Dec 13",
        when=PartialWhen(year=2026, month=12, day=13),
    )
    candidates = [_candidate("m1"), other]
    repo = InMemoryEventRepository(fail_on_write=2)
    use_case, _ = _use_case(repo=repo, extractor=ScriptedExtractor(candidates))
    messages = [_message("m1"), _message("m2", "Other Show, Dec 13")]
    with pytest.raises(OSError, match="disk full"):
        _ = use_case.ingest(messages, now=_NOW)
    assert len(repo.events) == 1  # the first write stuck

    result = use_case.ingest(messages, now=_NOW)
    assert (result.created, result.unchanged) == (1, 1)
    assert len(repo.events) == 2


def test_duplicate_event_inside_one_email_is_cited_once() -> None:
    twice = [_candidate(), _candidate()]
    use_case, repo = _use_case(extractor=ScriptedExtractor(twice))
    result = use_case.ingest([_message()], now=_NOW)
    assert (result.created, result.unchanged) == (1, 1)
    assert len(repo.events) == 1


def test_similarity_rung_cites_a_reworded_title() -> None:
    repo = InMemoryEventRepository()
    seed, _ = _use_case(
        repo=repo,
        extractor=ScriptedExtractor(
            [
                _candidate(
                    "m1", title="The Zebra Night Live", evidence="The Zebra Night Live, Dec 12"
                )
            ]
        ),
    )
    assert seed.ingest([_message("m1", "The Zebra Night Live, Dec 12")], now=_NOW).created == 1
    reworded = _candidate("m2", title="Zebra Night Live", evidence="Zebra Night Live, Dec 12")
    use_case, _ = _use_case(repo=repo, extractor=ScriptedExtractor([reworded]))
    result = use_case.ingest([_message("m2", "Zebra Night Live, Dec 12")], now=_NOW)
    assert (result.created, result.mentioned) == (0, 1)
    (event,) = repo.events.values()
    assert event.mentions[-1].match_rule is MatchRule.SIMILAR


class _RecordingIndex:
    """Wraps the difflib index and remembers which events it was asked to index."""

    def __init__(self) -> None:
        self.indexed: list[EventId] = []
        self._inner = DifflibSimilarEventIndex()

    def index(self, event: Event) -> None:
        self.indexed.append(event.id)
        self._inner.index(event)

    def similar(self, candidate: EventDraft, *, limit: int) -> list[tuple[EventId, float]]:
        return self._inner.similar(candidate, limit=limit)


def test_custom_similar_index_is_used_and_fed_new_events() -> None:
    index = _RecordingIndex()
    use_case, _ = _use_case(
        extractor=ScriptedExtractor([_candidate()]),
        similar_index=index,
        policy=IdentityPolicy(merge_at=0.99, link_at=0.9),
    )
    result = use_case.ingest([_message()], now=_NOW)
    assert index.indexed == list(result.created_ids)


def test_raw_message_is_stored_and_referenced_from_the_mention() -> None:
    raw = InMemoryRawMessageStore()
    repo = InMemoryEventRepository()
    ports = IngestPorts(
        repository=repo,
        reader=ScriptedReader(),
        extractor=ScriptedExtractor([_candidate()]),
        ids=SequentialIds(),
        raw_store=raw,
    )
    result = IngestEvents(ports, home_tz=_TZ).ingest([_message()], now=_NOW)
    assert result.created == 1
    (event,) = repo.events.values()
    ref = event.mentions[0].raw_ref
    assert ref is not None
    stored = raw.get(ref)
    assert stored is not None
    assert stored.message_id == "m1"
    assert raw.put(_message()) == ref  # idempotent
    assert raw.get(RawRef("nope")) is None


def test_listing_fields_reach_the_stored_event() -> None:
    candidate = _candidate(city="Los Angeles", tags=frozenset({"house"}), price="$20", age="21+")
    use_case, repo = _use_case(extractor=ScriptedExtractor([candidate]))
    assert use_case.ingest([_message()], now=_NOW).created == 1
    (event,) = repo.events.values()
    assert (event.city, event.tags, event.price, event.age) == (
        "Los Angeles",
        frozenset({"house"}),
        "$20",
        "21+",
    )


def test_showtimes_reach_the_stored_event_in_order_without_duplicates() -> None:
    when = PartialWhen(
        year=2026,
        month=12,
        day=12,
        time=time(12),
        showtimes=(time(12), time(19), time(15, 30), time(19)),
        raw_text="Sat Dec 12 - 12PM, 3:30PM, 7PM",
    )
    use_case, repo = _use_case(extractor=ScriptedExtractor([_candidate(when=when)]))
    assert use_case.ingest([_message()], now=_NOW).created == 1
    (event,) = repo.events.values()
    assert event.showtimes == (time(12), time(15, 30), time(19))


def test_a_single_time_is_not_a_showtime_list() -> None:
    when = PartialWhen(year=2026, month=12, day=12, time=time(12), showtimes=(time(12),))
    use_case, repo = _use_case(extractor=ScriptedExtractor([_candidate(when=when)]))
    assert use_case.ingest([_message()], now=_NOW).created == 1
    (event,) = repo.events.values()
    assert event.showtimes == ()


def test_consecutive_days_of_one_title_become_separate_events() -> None:
    """Sunday's and Monday's screenings of one film are two UUIDs; each is cited by its own
    mention, and re-ingesting changes nothing."""
    sunday = PartialWhen(year=2026, month=11, day=15, time=time(10), raw_text="Sun Nov 15 - 10AM")
    monday = PartialWhen(year=2026, month=11, day=16, time=time(12, 30), raw_text="Mon Nov 16")
    candidates = [
        _candidate(when=sunday, evidence="Band at Venue, Dec 12"),
        _candidate(when=monday, evidence="Band at Venue, Dec 12"),
    ]
    use_case, repo = _use_case(extractor=ScriptedExtractor(candidates))
    result = use_case.ingest([_message()], now=_NOW)
    assert (result.created, result.mentioned) == (2, 0)
    assert {local_date(e.when) for e in repo.events.values()} == {
        date(2026, 11, 15),
        date(2026, 11, 16),
    }
    assert all(len(e.mentions) == 1 for e in repo.events.values())
