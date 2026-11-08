"""How soon an item needs the user: one number, days until it is expected to be gone, for every kind of item.

A stated deadline is a survival curve that is a step: certainly open until the deadline, certainly closed after. An
open-ended item is the same thing with a smooth curve estimated from data: the share of such items still open
at each age (the caller's curve). Both give "days until it is expected to be gone" (for an open-ended one, the
median remaining life given that it is still open), so a deadline in 3 days and a 29-day-old item rank on one scale
and the smaller number comes first. There is no horizon and no per-kind cutoff: whichever will be gone soonest is the
highest priority.

One thing is not ranked at all: an open-ended item that is more likely closed than open (past the curve's median
lifespan), or whose deadline has passed. Those are not urgent, they are probably over, and ranking them by "remaining
life" would put the deadest items first. They sort last (``LIKELY_CLOSED``) and Home leaves them out.

The deadline bands match the real card's (0-1 critical and 2-3 urgent are both red, 4-7 soon is amber, a passed
deadline shows none; ``tracker.helpers._deadline_urgency`` is the card's own version and a test holds the two
together), and an open-ended item gets the same bands from its remaining days. No usable date means no signal.
Pure: the caller passes ``today``.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, TypedDict

from urgency.survival_curve import SurvivalCurve

_NEVER = 10 ** 9
LIKELY_CLOSED = 10 ** 6        # sorts after every item that can still be acted on; older ones sort later still
_RED_DAYS, _AMBER_DAYS = 3, 7


class UrgencyFields(TypedDict, total=False):
    """The keys ``item_urgency`` reads from a row (#1548); every other key is ignored. Dates are ISO ``YYYY-MM-DD``
    (a longer timestamp is cut to its date); a missing, empty or unparsable one counts as absent. ``closing_date`` wins
    over the other two; ``date_posted`` wins over ``first_seen_at``. ``tests/test_item_urgency_keys.py`` fails
    when the function reads a key that is not listed here."""

    closing_date: str | None
    date_posted: str | None
    first_seen_at: str | None


@dataclass(frozen=True)
class Urgency:
    """Days until the item is expected to be gone (``remaining``; smaller is more urgent) and the colour band."""

    remaining: int
    label: str
    band: str                      # "red" | "amber" | "" | "grey"
    kind: str                      # "deadline" | "age" | "none"

    @property
    def num(self) -> str:
        """The big figure in the row's urgency cell: ``5d``, or an en dash when there is no signal."""
        return self.label.split(" ", 1)[0] if self.kind != "none" else "–"

    @property
    def sub(self) -> str:
        """The small word under it: ``left`` (days to a deadline) or ``old`` (age of an open-ended item)."""
        return self.label.split(" ", 1)[1] if self.kind != "none" and " " in self.label else ""

    @property
    def likely_closed(self) -> bool:
        """An open-ended item more likely closed than open: not a priority, probably over."""
        return self.kind == "age" and self.remaining >= LIKELY_CLOSED


def _band(days: int) -> str:
    return "red" if days <= _RED_DAYS else "amber" if days <= _AMBER_DAYS else ""


def item_urgency(row: UrgencyFields | Mapping[str, Any], today: date, curve: SurvivalCurve) -> Urgency:
    """Days until an item is expected to be gone. A stated deadline counts down exactly; an open-ended item uses
    the median remaining life from ``curve`` at its age; a passed deadline or no usable date is no signal."""
    closing = _parse_date(row.get("closing_date"))
    if closing is not None:
        left = (closing - today).days
        if left < 0:
            return Urgency(_NEVER, "passed", "grey", "none")
        return Urgency(left, f"{left}d left", _band(left), "deadline")
    posted = _parse_date(row.get("date_posted")) or _parse_date(row.get("first_seen_at"))
    if posted is not None:
        age = max((today - posted).days, 0)
        remaining = curve.median_remaining(age)
        if remaining is None:
            return Urgency(LIKELY_CLOSED + age, f"{age}d old", "grey", "age")
        days = max(1, round(remaining))
        return Urgency(days, f"{age}d old", _band(days), "age")
    return Urgency(_NEVER, "", "grey", "none")


def _parse_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
