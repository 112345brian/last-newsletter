"""Tell the owner about newly unwell sources, once, through whatever notifier is wired in.

The notifier and the record of what was already announced are ports; this holds the policy. If the
notifier fails nothing is recorded as announced, so the next run tries again instead of the news
being lost.
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from concert_tracker_app.health_report import alert_line
from concert_tracker_core.source_alerts import NotifierError, plan_announcements

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from concert_tracker_app.health_report import HealthAssessment
    from concert_tracker_core.source_alerts import SourceAlert
    from concert_tracker_core.source_runs import HealthLevel


class Notifier(Protocol):
    def notify(self, title: str, message: str) -> None:
        """Show `message` to the owner. Raises `NotifierError` when it could not."""
        ...


class AlertLog(Protocol):
    """What has already been announced, so the same trouble is not announced every day."""

    def announced(self) -> Mapping[str, HealthLevel]:
        """The level each source was last announced at, keyed by `source_key`."""
        ...

    def record(self, alert: SourceAlert) -> None: ...

    def clear(self, source_keys: Collection[str]) -> None: ...


@dataclass(frozen=True, slots=True)
class AnnounceOutcome:
    announced: tuple[SourceAlert, ...]
    delivery_error: str = ""


def alert_message(alerts: tuple[SourceAlert, ...]) -> tuple[str, str]:
    """A notification's title and body for `alerts`."""
    noun = "source needs" if len(alerts) == 1 else "sources need"
    return f"Concert Tracker: {len(alerts)} {noun} a look", "\n".join(alert_line(a) for a in alerts)


class AnnounceUnwell:
    def __init__(self, notifier: Notifier, log: AlertLog) -> None:
        self._notifier = notifier
        self._log = log

    def execute(self, assessment: HealthAssessment) -> AnnounceOutcome:
        plan = plan_announcements(assessment.unwell, assessment.assessed, self._log.announced())
        if plan.to_clear:
            self._log.clear(plan.to_clear)
        if not plan.to_announce:
            return AnnounceOutcome(())
        title, message = alert_message(plan.to_announce)
        try:
            self._notifier.notify(title, message)
        except NotifierError as error:
            return AnnounceOutcome((), str(error) or error.__class__.__name__)
        for alert in plan.to_announce:
            self._log.record(alert)
        return AnnounceOutcome(plan.to_announce)
