"""A survival curve (the share of items still open at each age) and the Kaplan-Meier estimator that learns one.

Pure: no I/O, no clock, no ambient randomness (the bootstrap takes an ``IndexSource``, e.g. a ``random.Random``). ``item_urgency`` ranks
with a ``SurvivalCurve``; ``urgency_model_gate`` decides whether a curve fitted here may replace the hand-calibrated
one. Plain Python on purpose: the analysis behind the design used ``lifelines`` only in a throwaway environment.

The estimator takes ``Spell`` records, one per item: the age at which we started watching it (``entry``, later
than 0 when an item was already posted for a while the first time we saw it: left truncation, so such an item
never counts as "at risk" before the age it was first seen), the age at which we stopped (``exit``), and whether
that stop was a closing (``event``) or only the end of what we know (right-censored). A closing that is only known
to lie between a last live check and the first closed check is entered at the middle of that bracket; the bracket is
a few days wide (the checker's cadence), which moves a median by about half of it.
"""
from __future__ import annotations

__arbor__ = {"ring": "core"}

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class SurvivalCurve:
    """The share of items still open at each age: ``(age_days, share)`` points, ages increasing, shares not
    increasing. Between points the share is interpolated; before the first it is the first, after the last the last."""

    points: tuple[tuple[int, float], ...]

    @property
    def last_age(self) -> int:
        return self.points[-1][0]

    def open_share(self, age: float) -> float:
        pts = self.points
        if age <= pts[0][0]:
            return pts[0][1]
        for (a0, s0), (a1, s1) in zip(pts, pts[1:]):
            if age <= a1:
                return s0 + (s1 - s0) * (age - a0) / (a1 - a0)
        return pts[-1][1]

    def age_at(self, share: float) -> float | None:
        """The first age at which the open share falls to ``share``; ``None`` when it never does."""
        pts = self.points
        if pts[0][1] <= share:
            return float(pts[0][0])
        for (a0, s0), (a1, s1) in zip(pts, pts[1:]):
            if s1 <= share:
                return a0 + (a1 - a0) * (s0 - share) / (s0 - s1) if s0 != s1 else float(a1)
        return None

    def median_lifespan(self) -> int:
        """The age by which half of these items have closed."""
        at = self.age_at(0.5)
        return round(at) if at is not None else self.last_age

    def median_remaining(self, age: float) -> float | None:
        """Days until half of the items still open at ``age`` are gone, or ``None`` when the item is more likely
        closed than open already (the open share has fallen below one half)."""
        share = self.open_share(age)
        if share < 0.5:
            return None
        at = self.age_at(share / 2)
        # The curve may flatten above half of the current share (the tail of very long-lived items): say so with a
        # long but finite number, so such an item is not the most urgent thing on the board.
        return (at - age) if at is not None else float(self.last_age - age) + 365.0


@dataclass(frozen=True)
class Spell:
    """One item's time under observation, in days of age. ``event`` is True when it closed at ``exit``, False when
    it was still open as far as we know (right-censored)."""

    entry: float
    exit: float
    event: bool


def _day(age: float) -> int:
    return int(max(age, 0.0) + 0.5)


def kaplan_meier(spells: Sequence[Spell]) -> SurvivalCurve:
    """The Kaplan-Meier curve of ``spells``, with right censoring and left truncation. No closing at all gives the flat
    curve ``((0, 1.0),)`` (nothing has been seen to close, so nothing is claimed about when it will)."""
    entries = sorted(_day(s.entry) for s in spells)
    exits = sorted(_day(s.exit) for s in spells)
    closings: dict[int, int] = {}
    for s in spells:
        if s.event:
            closings[_day(s.exit)] = closings.get(_day(s.exit), 0) + 1
    share = 1.0
    points: list[tuple[int, float]] = [(0, 1.0)]
    for day in sorted(closings):
        at_risk = bisect_right(entries, day) - bisect_left(exits, day)
        if at_risk <= 0:
            continue
        share *= 1.0 - min(closings[day], at_risk) / at_risk
        if day == 0:
            points[0] = (0, share)
        else:
            points.append((day, share))
    return SurvivalCurve(points=tuple(points))


class IndexSource(Protocol):
    """What the bootstrap needs from a random source; a ``random.Random`` satisfies it."""

    def randrange(self, stop: int, /) -> int: ...


def median_age(curve: SurvivalCurve) -> float | None:
    """The age at which half of the items have closed, or ``None`` when the curve never gets there."""
    return curve.age_at(0.5)


def bootstrap_median_interval(
    spells: Sequence[Spell], rng: IndexSource, *, resamples: int = 200, level: float = 0.95,
) -> tuple[float | None, float | None]:
    """A percentile bootstrap interval for the median lifespan: resample the items with replacement, refit, take the
    middle ``level`` of the medians. A resample whose curve never reaches one half has no median and counts as
    unboundedly large, so an end of the interval is ``None`` (unbounded) when more than the tail share of resamples
    have none. Fewer than two spells, or no closing, gives ``(None, None)``."""
    if len(spells) < 2 or not any(s.event for s in spells):
        return None, None
    medians: list[float] = []
    for _ in range(resamples):
        sample = [spells[rng.randrange(len(spells))] for _ in spells]
        m = median_age(kaplan_meier(sample))
        medians.append(float("inf") if m is None else m)
    medians.sort()
    tail = (1.0 - level) / 2.0
    lo = medians[min(int(tail * resamples), resamples - 1)]
    hi = medians[min(int((1.0 - tail) * resamples), resamples - 1)]
    return (None if lo == float("inf") else lo), (None if hi == float("inf") else hi)
