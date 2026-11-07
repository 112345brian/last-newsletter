"""The survival curve and the Kaplan-Meier estimator behind the learned urgency model (urgency.survival_curve)."""
from __future__ import annotations

import random

import pytest

from urgency.survival_curve import Spell, SurvivalCurve, bootstrap_median_interval, kaplan_meier, median_age


# The same points as the app's job-calibrated curve (tests/test_open_ended_curve.py pins that one); a lib test cannot import the app.
OPEN_ENDED_CURVE = SurvivalCurve(points=((0, 1.0), (7, 1.0), (22, 0.71), (45, 0.24), (75, 0.22), (90, 0.15)))


def _closed(*exits: float, entry: float = 0) -> list[Spell]:
    return [Spell(entry, e, True) for e in exits]


def _open(*exits: float, entry: float = 0) -> list[Spell]:
    return [Spell(entry, e, False) for e in exits]


# --- the curve (moved here from item_urgency; behaviour pinned) ----------------------------------------------------

def test_the_provisional_curve_keeps_its_hand_calibrated_points():
    assert OPEN_ENDED_CURVE.points == ((0, 1.0), (7, 1.0), (22, 0.71), (45, 0.24), (75, 0.22), (90, 0.15))
    assert OPEN_ENDED_CURVE.median_lifespan() == 32


@pytest.mark.parametrize("age, share", [(-5, 1.0), (0, 1.0), (7, 1.0), (14.5, 0.855), (22, 0.71), (200, 0.15)])
def test_open_share_interpolates_and_clamps(age, share):
    assert OPEN_ENDED_CURVE.open_share(age) == pytest.approx(share)


def test_median_remaining_is_none_once_more_likely_closed_than_open():
    assert OPEN_ENDED_CURVE.median_remaining(60) is None
    assert OPEN_ENDED_CURVE.median_remaining(0) is not None


# --- Kaplan-Meier -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("spells, points", [
    ([], ((0, 1.0),)),                                                            # nothing observed: nothing claimed
    (_open(5, 9, 30), ((0, 1.0),)),                                               # nobody closed: flat
    (_closed(5, 10), ((0, 1.0), (5, 0.5), (10, 0.0))),                           # no censoring: the empirical share
    (_closed(5) + _open(7) + _closed(10), ((0, 1.0), (5, 2 / 3), (10, 0.0))),    # the censored one leaves the risk set at 7
    (_closed(5, 5, 8), ((0, 1.0), (5, 1 / 3), (8, 0.0))),                        # ties close together
    (_closed(0, 4), ((0, 0.5), (4, 0.0))),                                        # a closing on the first day
])
def test_kaplan_meier_table(spells, points):
    got = kaplan_meier(spells).points
    assert [a for a, _ in got] == [a for a, _ in points]
    assert [s for _, s in got] == pytest.approx([s for _, s in points])


def test_a_censored_listing_is_not_counted_as_closed_before_its_censoring_day():
    # Three listings: one closes at 5, one is only known open until 6 (censored), one closes at 8.
    curve = kaplan_meier(_closed(5, 8) + _open(6))
    assert curve.open_share(5) == pytest.approx(2 / 3)       # at day 5 all three are at risk
    assert curve.open_share(8) == pytest.approx(0.0)          # at day 8 only the last is at risk: it closes


def test_left_truncation_keeps_a_listing_out_of_the_risk_set_before_it_was_first_seen():
    # B was already 20 days old when first seen, so it cannot have been at risk when A closed at day 5.
    with_late = kaplan_meier([Spell(0, 5, True), Spell(20, 30, True)])
    assert with_late.open_share(5) == pytest.approx(0.0)      # only A was at risk at 5
    ignoring_entry = kaplan_meier([Spell(0, 5, True), Spell(0, 30, True)])
    assert ignoring_entry.open_share(5) == pytest.approx(0.5)  # the mistake this guards against


def test_the_curve_never_rises_and_its_ages_strictly_increase():
    rng = random.Random(3)
    spells = [Spell(rng.randint(0, 5), rng.randint(6, 60), rng.random() < 0.6) for _ in range(300)]
    pts = kaplan_meier(spells).points
    assert all(b[0] > a[0] and b[1] <= a[1] for a, b in zip(pts, pts[1:]))


def test_fractional_closing_ages_round_to_whole_days():
    assert kaplan_meier(_closed(4.5, 10.4)).points[1][0] == 5


def test_median_age_is_none_when_the_curve_never_reaches_one_half():
    assert median_age(kaplan_meier(_closed(10) + _open(*[20] * 9))) is None
    assert median_age(kaplan_meier(_closed(10, 20, 30))) == pytest.approx(15)


# --- bootstrap --------------------------------------------------------------------------------------------------------

def _population(n: int, seed: int) -> list[Spell]:
    rng = random.Random(seed)
    return [Spell(0, rng.randint(10, 50), True) for _ in range(n)]


def test_the_bootstrap_interval_is_reproducible_and_brackets_the_median():
    spells = _population(400, 1)
    first = bootstrap_median_interval(spells, random.Random(7), resamples=100)
    again = bootstrap_median_interval(spells, random.Random(7), resamples=100)
    assert first == again
    lo, hi = first
    assert lo <= median_age(kaplan_meier(spells)) <= hi


def test_the_interval_narrows_with_more_data():
    wide = bootstrap_median_interval(_population(30, 2), random.Random(1), resamples=100)
    narrow = bootstrap_median_interval(_population(600, 2), random.Random(1), resamples=100)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


@pytest.mark.parametrize("spells", [[], _closed(5), _open(3, 9, 12)])
def test_the_interval_is_undefined_without_two_listings_and_a_closing(spells):
    assert bootstrap_median_interval(spells, random.Random(0)) == (None, None)


def test_an_interval_whose_resamples_mostly_lack_a_median_is_unbounded():
    spells = _closed(10) + _open(*[30] * 40)           # the curve never reaches one half
    assert bootstrap_median_interval(spells, random.Random(0), resamples=50) == (None, None)
