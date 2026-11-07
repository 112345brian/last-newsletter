from datetime import UTC, date, datetime
from uuid import UUID

from last_newsletter_core.event_identity import IdentityPolicy, identify
from last_newsletter_core.events import (
    AllDay,
    EntityRef,
    EntityRole,
    Event,
    EventDraft,
    EventId,
    EventKind,
    MatchRule,
    Mention,
)

_T = datetime(2026, 11, 6, tzinfo=UTC)


def _id(n: int) -> EventId:
    return EventId(UUID(int=n))


def _venue(name: str) -> tuple[EntityRef, ...]:
    return (EntityRef(name=name, role=EntityRole.VENUE),) if name else ()


def _event(
    n: int,
    *,
    title: str = "Band at Venue",
    day: date = date(2026, 12, 12),
    venue: str = "The Venue",
    uid: str | None = None,
    url: str | None = None,
    night_of: date | None = None,
) -> Event:
    return Event(
        id=_id(n),
        kind=EventKind.EVENT,
        title=title,
        summary="",
        when=AllDay(day),
        entities=_venue(venue),
        mentions=(
            Mention(
                message_id=f"m{n}",
                seen_at=_T,
                source="s",
                evidence="e",
                match_rule=MatchRule.NEW,
                cited_event_id=_id(n),
            ),
        ),
        first_seen=_T,
        last_seen=_T,
        uid=uid,
        url=url,
        night_of=night_of,
    )


def _draft(
    *,
    title: str = "Band at Venue",
    day: date = date(2026, 12, 12),
    venue: str = "The Venue",
    uid: str | None = None,
    url: str | None = None,
    night_of: date | None = None,
) -> EventDraft:
    return EventDraft(
        kind=EventKind.EVENT,
        title=title,
        summary="",
        when=AllDay(day),
        evidence="e",
        entities=_venue(venue),
        uid=uid,
        url=url,
        night_of=night_of,
    )


def test_empty_pool_is_new() -> None:
    decision = identify(_draft(), [])
    assert (decision.rule, decision.event, decision.possible_duplicates) == (
        MatchRule.NEW,
        None,
        (),
    )


def test_uid_wins_even_when_everything_else_changed() -> None:
    existing = _event(1, uid="u1", title="Old name", day=date(2026, 12, 20))
    decision = identify(_draft(uid="u1"), [existing, _event(2)])
    assert decision.rule is MatchRule.UID
    assert decision.event == existing


def test_two_events_with_one_uid_stay_separate_and_linked() -> None:
    decision = identify(_draft(uid="u"), [_event(1, uid="u"), _event(2, uid="u")])
    assert decision.rule is MatchRule.NEW
    assert decision.event is None
    assert decision.possible_duplicates == (_id(1), _id(2))


def test_url_match_needs_a_path_and_a_nearby_date() -> None:
    url = "https://example.com/events/42"
    same = _event(1, url=url, title="Different words entirely", venue="")
    assert identify(_draft(url=url), [same]).rule is MatchRule.URL
    far = _event(2, url=url, day=date(2027, 3, 1), title="Other", venue="")
    decision = identify(_draft(url=url, title="Zzz"), [far])
    assert decision.rule is MatchRule.NEW
    assert decision.possible_duplicates == (_id(2),)
    home = _event(3, url="https://example.com", title="Other", venue="")
    assert identify(_draft(url="https://example.com", title="Zzz"), [home]).rule is MatchRule.NEW


def test_title_date_venue_matches_ignoring_case_and_accents() -> None:
    existing = _event(1, title="BÂND at Venue!")
    decision = identify(_draft(title="band at venue"), [existing])
    assert decision.rule is MatchRule.TITLE_DATE_VENUE
    assert decision.event == existing


def test_consecutive_listed_days_of_one_title_stay_separate() -> None:
    """A film screening on Sunday and again on Monday is two events, not one cited twice."""
    sunday = _event(1, day=date(2026, 11, 15))
    decision = identify(_draft(day=date(2026, 11, 16)), [sunday])
    assert (decision.rule, decision.event, decision.possible_duplicates) == (
        MatchRule.NEW,
        None,
        (),
    )
    tuesday = _event(2, day=date(2026, 11, 17))
    assert identify(_draft(day=date(2026, 11, 16)), [sunday, tuesday]).rule is MatchRule.NEW


def test_one_day_off_matches_only_for_an_after_midnight_listing() -> None:
    """ "Sat 1:30am" is Friday night: the listed date is uncertain, so one day off may match."""
    night = _event(1, day=date(2026, 12, 13), night_of=date(2026, 12, 12))
    assert identify(_draft(day=date(2026, 12, 12)), [night]).rule is MatchRule.TITLE_DATE_VENUE
    late_draft = _draft(day=date(2026, 12, 13), night_of=date(2026, 12, 12))
    plain = _event(2, day=date(2026, 12, 12))
    assert identify(late_draft, [plain]).rule is MatchRule.TITLE_DATE_VENUE
    assert identify(_draft(day=date(2026, 12, 11)), [night]).rule is MatchRule.NEW


def test_same_title_on_a_different_date_is_a_different_event() -> None:
    decision = identify(_draft(day=date(2026, 12, 19)), [_event(1)])
    assert (decision.rule, decision.possible_duplicates) == (MatchRule.NEW, ())


def test_different_venue_is_not_a_match_and_missing_venue_is_only_linked() -> None:
    other_venue = identify(_draft(venue="Elsewhere"), [_event(1)])
    assert (other_venue.rule, other_venue.possible_duplicates) == (MatchRule.NEW, ())
    no_venue = identify(_draft(venue=""), [_event(1)])
    assert no_venue.rule is MatchRule.NEW
    assert no_venue.possible_duplicates == (_id(1),)


def test_similarity_rung_is_consulted_only_after_deterministic_ones() -> None:
    calls: list[int] = []

    def similar() -> list[tuple[Event, float]]:
        calls.append(1)
        return [(_event(9), 1.0)]

    assert identify(_draft(), [_event(1)], similar=similar).rule is MatchRule.TITLE_DATE_VENUE
    assert calls == []
    assert identify(_draft(title="Quite different"), [], similar=similar).event is not None
    assert calls == [1]


def test_similarity_merges_high_scores_links_middling_and_ignores_low() -> None:
    policy = IdentityPolicy(merge_at=0.9, link_at=0.7)
    draft = _draft(title="Zebra Night")

    def hit(score: float, day: date = date(2026, 12, 12)) -> list[tuple[Event, float]]:
        return [(_event(5, day=day), score)]

    merged = identify(draft, [], similar=lambda: hit(0.95), policy=policy)
    assert (merged.rule, merged.event) == (MatchRule.SIMILAR, _event(5))
    linked = identify(draft, [], similar=lambda: hit(0.8), policy=policy)
    assert (linked.rule, linked.possible_duplicates) == (MatchRule.NEW, (_id(5),))
    ignored = identify(draft, [], similar=lambda: hit(0.3), policy=policy)
    assert (ignored.rule, ignored.possible_duplicates) == (MatchRule.NEW, ())
    far = identify(draft, [], similar=lambda: hit(0.99, date(2027, 5, 5)), policy=policy)
    assert (far.rule, far.event) == (MatchRule.NEW, None)  # linked, never merged across dates


def test_similarity_never_merges_across_conflicting_venues() -> None:
    policy = IdentityPolicy(merge_at=0.9, link_at=0.7)
    decision = identify(
        _draft(title="Zebra Night"),
        [],
        similar=lambda: [(_event(5, venue="Elsewhere"), 0.99)],
        policy=policy,
    )
    assert decision.rule is MatchRule.NEW
    assert decision.possible_duplicates == (_id(5),)


def test_two_high_similarity_hits_are_ambiguous() -> None:
    decision = identify(
        _draft(title="Zebra Night"),
        [],
        similar=lambda: [(_event(5), 0.99), (_event(6), 0.98)],
    )
    assert decision.rule is MatchRule.NEW
    assert decision.possible_duplicates == (_id(5), _id(6))


def test_similar_event_on_another_date_is_linked_not_merged() -> None:
    """Same series, different date (and a different title): never a match, but worth a link."""
    policy = IdentityPolicy(merge_at=0.9, link_at=0.7)
    week_later = _event(5, title="Zebra Night Vol 2", day=date(2026, 12, 19))
    decision = identify(
        _draft(title="Zebra Night Vol 3"), [], similar=lambda: [(week_later, 0.97)], policy=policy
    )
    assert (decision.rule, decision.event) == (MatchRule.NEW, None)
    assert decision.possible_duplicates == (_id(5),)


def test_same_title_on_another_date_is_not_linked_by_similarity() -> None:
    policy = IdentityPolicy(merge_at=0.9, link_at=0.7)
    other_day = _event(5, day=date(2026, 12, 19))
    decision = identify(_draft(), [], similar=lambda: [(other_day, 0.99)], policy=policy)
    assert (decision.rule, decision.possible_duplicates) == (MatchRule.NEW, ())
