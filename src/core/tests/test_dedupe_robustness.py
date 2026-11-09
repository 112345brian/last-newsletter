"""Robustness checks for the identity ladder, beyond the hand-labelled pairs.

Four kinds of check, all deterministic and fast:

1. Invariants: statements that must hold for any listing, tried over generated variations.
2. Symmetry: whether a pair merges must not depend on which email arrived first.
3. Scale: a few hundred distinct events together produce no wrong merge, and each re-listing finds
   exactly its own event.
4. Mutants: deliberate breaks of each rule must be noticed by the labelled pairs. This is what keeps
   the pairs honest: a fixture set that every broken version still passes is not testing anything.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from datetime import time as clock
from itertools import product
from typing import cast

import pytest
from test_dedupe_pair_fixtures import (
    ALL,
    FRI,
    Listing,
    Pair,
    _draft,
    _event,
)

from last_newsletter_core import event_identity
from last_newsletter_core.event_identity import identify
from last_newsletter_core.events import MatchRule

_8PM, _9PM = clock(20), clock(21)


def _merges(known: Listing, incoming: Listing) -> bool:
    return identify(_draft(incoming), [_event(1, known)]).event is not None


# ---------------------------------------------------------------------------------- 1. invariants

_BASES = (
    Listing("Mdou Moctar", FRI, "The Fonda", (_8PM,)),
    Listing("Open Mic Night", FRI, "Hotel Cafe"),
    Listing("La Bola Negra screening at The Frida Cinema", FRI, "The Frida Cinema", (_8PM, _9PM)),
    Listing("Café du Nord Presents: Dub Club", FRI, "Café du Nord", (_9PM,)),
)

_RESPELLINGS: tuple[Callable[[str], str], ...] = (
    str.upper,
    str.lower,
    str.title,
    lambda t: f"  {t}  ",
    lambda t: t.replace(" ", "  "),
    lambda t: f"{t}!",
    lambda t: t.replace("é", "e"),
)


@pytest.mark.parametrize(("base", "respell"), list(product(_BASES, _RESPELLINGS)))
def test_respelling_title_and_venue_never_hides_a_duplicate(
    base: Listing, respell: Callable[[str], str]
) -> None:
    again = replace(base, title=respell(base.title), venue=respell(base.venue))
    assert _merges(base, again)


@pytest.mark.parametrize(
    ("base", "offset"), list(product(_BASES, (1, 2, 3, 7, 30, 365, -1, -7, -30)))
)
def test_another_date_is_never_the_same_event(base: Listing, offset: int) -> None:
    other = replace(base, day=base.day + timedelta(days=offset))
    assert not _merges(base, other)


@pytest.mark.parametrize("base", _BASES)
def test_a_conflicting_venue_blocks_every_title_relation(base: Listing) -> None:
    other_venue = "A Completely Different Room"
    for title in (base.title, base.title.upper(), f"{base.title} with special guests"):
        assert not _merges(base, replace(base, title=title, venue=other_venue))


@pytest.mark.parametrize("base", _BASES)
def test_a_listing_with_no_showtime_in_common_is_only_linked_never_merged(base: Listing) -> None:
    if not base.times:
        pytest.skip("rung 3 handles listings without showtimes")
    longer = replace(base, title=f"{base.title} live", venue="", times=(clock(2, 30),))
    decision = identify(_draft(longer), [_event(1, base)])
    assert decision.event is None
    assert [str(i) for i in decision.possible_duplicates] != []


def test_two_candidates_sharing_a_showtime_stay_separate_and_both_are_linked() -> None:
    one = Listing("La Bola Negra", FRI, "", (_8PM,))
    two = Listing("La Bola Negra Encore", FRI, "", (_8PM,))
    incoming = Listing("La Bola Negra Encore Night", FRI, "", (_8PM, _9PM))
    decision = identify(_draft(incoming), [_event(1, one), _event(2, two)])
    assert decision.event is None
    assert len(decision.possible_duplicates) == 2


def test_a_title_related_to_only_one_known_event_merges_with_that_one() -> None:
    one = Listing("La Bola Negra", FRI, "", (_8PM,))
    two = Listing("Jazz Quartet", FRI, "", (_8PM,))
    decision = identify(
        _draft(Listing("la bola negra preview", FRI, "", (_8PM,))), [_event(1, one), _event(2, two)]
    )
    assert decision.event is not None
    assert decision.event.title == "La Bola Negra"


# ----------------------------------------------------------------------------------- 2. symmetry


@pytest.mark.parametrize("pair", ALL, ids=[p.name for p in ALL])
def test_arrival_order_does_not_change_whether_two_listings_merge(pair: Pair) -> None:
    assert _merges(pair.known, pair.incoming) == _merges(pair.incoming, pair.known)


# ----------------------------------------------------------------------------------- 3. at scale

_ACTS = (
    "Mdou Moctar",
    "Open Mic Night",
    "La Bola Negra",
    "Dub Club",
    "Jazz Quartet",
    "Silent Disco",
    "Salsa Social",
    "Synth Swap",
    "Poetry Slam",
    "Comedy Cellar",
    "Techno Tuesday",
    "Folk Revival",
    "Drag Brunch",
    "Vinyl Market",
    "Karaoke Royale",
    "Roller Rink Night",
    "Trivia Showdown",
    "Gospel Hour",
    "Metal Monday",
    "Swing Dance Lab",
)
_ROOMS = ("The Fonda", "Hotel Cafe", "The Echo", "Zebulon", "Blue Whale", "The Mint")


def _population() -> list[Listing]:
    start = date(2026, 11, 13)
    out: list[Listing] = []
    for i, (act, room) in enumerate(product(_ACTS, _ROOMS)):
        day = start + timedelta(days=i % 9)
        out.append(Listing(act, day, room, ((_8PM,), (_9PM,), ())[i % 3]))
    return out


def test_each_relisting_finds_exactly_its_own_event_among_many() -> None:
    population = _population()
    pool = [_event(n + 1, item) for n, item in enumerate(population)]
    for n, item in enumerate(population):
        again = replace(item, title=item.title.upper(), venue=item.venue.lower())
        decision = identify(_draft(again), pool)
        assert decision.event is not None, item
        assert decision.event.id == pool[n].id, item


def test_no_event_in_a_large_pool_is_merged_with_a_different_event() -> None:
    population = _population()
    pool = [_event(n + 1, item) for n, item in enumerate(population)]
    wrong = []
    for n, item in enumerate(population):
        rest = pool[:n] + pool[n + 1 :]
        decision = identify(_draft(item), rest)
        # Every other event differs by act, room or date. If one matches, name it.
        if decision.event is not None:
            wrong.append((item.title, item.venue, decision.event.title))
    assert wrong == []


# ------------------------------------------------------------------------------------ 4. mutants


def _labels() -> list[tuple[str, bool]]:
    return [(p.name, _merges(p.known, p.incoming)) for p in ALL]


def _title_rule_without_containment(a: str, b: str) -> MatchRule | None:
    rule = _original_title_rule(a, b)
    return None if rule is MatchRule.SAME_DATE_TITLE_CONTAINS else rule


def _title_rule_without_similarity(a: str, b: str) -> MatchRule | None:
    rule = _original_title_rule(a, b)
    return None if rule is MatchRule.SAME_DATE_TITLE_SIMILAR else rule


_original_title_rule = cast(
    "Callable[[str, str], MatchRule | None]", vars(event_identity)["_title_rule"]
)

# name -> (attribute, replacement). Each is a plausible slip someone could make while "improving"
# the ladder; each must change at least one verdict in the labelled pairs.
_MUTANTS = {
    "venue conflicts ignored": ("_venues_conflict", lambda *_: False),
    "short titles trusted": ("_MIN_TITLE_CHARS", 1),
    "title similarity loosened": ("_TITLE_NEAR", 0.4),
    "title similarity removed": ("_title_rule", _title_rule_without_similarity),
    "title containment removed": ("_title_rule", _title_rule_without_containment),
    "showtimes always count as shared": ("_clock_times", lambda _item: frozenset({clock(0)})),
    "dates ignored": ("_same_day", lambda *_: True),
    "after-midnight window removed": ("_WINDOW_DAYS", 0),
}


@pytest.mark.parametrize("name", sorted(_MUTANTS))
def test_the_labelled_pairs_notice_when_a_rule_is_broken(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _labels()
    attribute, replacement = _MUTANTS[name]
    monkeypatch.setattr(event_identity, attribute, replacement)
    after = _labels()
    flipped = [b[0] for b, a in zip(before, after, strict=True) if b[1] != a[1]]
    assert flipped, f"mutant '{name}' changed no verdict: the pairs cannot see this rule"
