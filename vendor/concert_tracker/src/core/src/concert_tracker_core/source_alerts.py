"""Which unhealthy sources are worth telling the owner about, without repeating themselves.

Pure rules, no I/O. `judge_health` says how a source is; this decides when saying so is news.
A source is announced the first time it is unwell, and again only if it gets worse (degraded, then
failing). Once it is well again its record is cleared, so a relapse is news again. A source not
looked at this time keeps its record: silence about it is not recovery.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass
from typing import TYPE_CHECKING

from concert_tracker_core.source_runs import HealthLevel, source_key

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence
    from datetime import datetime

UNWELL = (HealthLevel.DEGRADED, HealthLevel.FAILING)
_SEVERITY = {HealthLevel.DEGRADED: 1, HealthLevel.FAILING: 2}


class NotifierError(Exception):
    """A notification could not be delivered."""


@dataclass(frozen=True, slots=True)
class SourceAlert:
    """An unwell source: why, the last error it gave, and when it last found events."""

    source: str
    level: HealthLevel
    reasons: tuple[str, ...]
    last_error: str = ""
    last_good: datetime | None = None

    def __post_init__(self) -> None:
        if self.level not in UNWELL:
            msg = f"{self.source!r} is {self.level.value}; only unwell sources are alerts"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class AnnouncementPlan:
    to_announce: tuple[SourceAlert, ...]
    to_clear: tuple[str, ...]


def plan_announcements(
    unwell: Sequence[SourceAlert],
    assessed: Collection[str],
    announced: Mapping[str, HealthLevel],
) -> AnnouncementPlan:
    """What to announce now and which earlier announcements are over.

    `assessed` is every source looked at this time (well or not); `announced` is the level each
    source was last announced at, keyed by `source_key`.
    """
    to_announce = tuple(
        alert
        for alert in unwell
        if source_key(alert.source) not in announced
        or _SEVERITY[alert.level] > _SEVERITY.get(announced[source_key(alert.source)], 0)
    )
    still_unwell = {source_key(a.source) for a in unwell}
    looked_at = {source_key(name) for name in assessed}
    to_clear = tuple(sorted(key for key in announced if key in looked_at - still_unwell))
    return AnnouncementPlan(to_announce, to_clear)
