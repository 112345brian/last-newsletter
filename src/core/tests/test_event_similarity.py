from datetime import UTC, date, datetime
from uuid import UUID

from last_newsletter_core.event_similarity import DifflibSimilarEventIndex
from last_newsletter_core.events import (
    AllDay,
    Event,
    EventDraft,
    EventId,
    EventKind,
    MatchRule,
    Mention,
)

_T = datetime(2026, 11, 6, tzinfo=UTC)


def _event(n: int, title: str) -> Event:
    event_id = EventId(UUID(int=n))
    mention = Mention("m", _T, "s", "e", MatchRule.NEW, event_id)
    return Event(
        id=event_id,
        kind=EventKind.EVENT,
        title=title,
        summary="",
        when=AllDay(date(2026, 12, 12)),
        mentions=(mention,),
        first_seen=_T,
        last_seen=_T,
    )


def _draft(title: str) -> EventDraft:
    return EventDraft(
        kind=EventKind.EVENT, title=title, summary="", when=AllDay(date(2026, 12, 12)), evidence="e"
    )


def test_most_alike_first_limited_and_scores_in_unit_range() -> None:
    index = DifflibSimilarEventIndex()
    for n, title in enumerate(["Zebra Night Live", "Quiet Jazz Brunch", "Zebra Night"], start=1):
        index.index(_event(n, title))
    hits = index.similar(_draft("zebra night live"), limit=2)
    assert [h[0] for h in hits] == [EventId(UUID(int=1)), EventId(UUID(int=3))]
    assert hits[0][1] == 1.0
    assert all(0.0 <= score <= 1.0 for _, score in hits)


def test_empty_index_and_nonpositive_limit_return_nothing() -> None:
    index = DifflibSimilarEventIndex()
    assert index.similar(_draft("x"), limit=5) == []
    index.index(_event(1, "x"))
    assert index.similar(_draft("x"), limit=0) == []


def test_reindexing_replaces_instead_of_duplicating() -> None:
    index = DifflibSimilarEventIndex()
    index.index(_event(1, "Old title"))
    index.index(_event(1, "New title"))
    assert len(index.similar(_draft("New title"), limit=5)) == 1
