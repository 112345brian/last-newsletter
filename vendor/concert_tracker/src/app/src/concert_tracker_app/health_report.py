"""Which sources are unwell right now, read from the run history, and how to say so."""

from __future__ import annotations

__arbor__ = {"ring": "app"}

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from concert_tracker_core.source_alerts import UNWELL, SourceAlert
from concert_tracker_core.source_runs import HISTORY_WINDOW, RunStatus, judge_health

if TYPE_CHECKING:
    from collections.abc import Sequence

    from concert_tracker_app.run_sources import RunHistory
    from concert_tracker_core.source_runs import SourceCatalog


@dataclass(frozen=True, slots=True)
class HealthAssessment:
    """Every source looked at, and the ones among them that are unwell."""

    assessed: tuple[str, ...]
    unwell: tuple[SourceAlert, ...]


def assess_health(
    catalog: SourceCatalog, history: RunHistory | None, only: Sequence[str] = ()
) -> HealthAssessment:
    """Judge the named sources (else every enabled one) by their latest recorded run.

    A source that has never run is not unwell, just unknown, so it is not an alert.
    """
    specs = catalog.named(only) if only else catalog.enabled()
    unwell: list[SourceAlert] = []
    for spec in specs:
        recent = history.recent(spec.name, HISTORY_WINDOW + 1) if history is not None else []
        if not recent:
            continue
        health = judge_health(recent[0], recent[1:])
        if health.level not in UNWELL:
            continue
        last_good = next((o.started_at for o in recent if o.status is RunStatus.OK), None)
        error = recent[0].error if recent[0].errored else ""
        unwell.append(SourceAlert(spec.name, health.level, health.reasons, error, last_good))
    return HealthAssessment(tuple(s.name for s in specs), tuple(unwell))


def _good(alert: SourceAlert) -> str:
    if alert.last_good is None:
        return "no good run on record"
    return f"last good run {alert.last_good.strftime('%Y-%m-%d %H:%M')}"


def alert_line(alert: SourceAlert) -> str:
    why = "; ".join(alert.reasons)
    error = f" ({alert.last_error})" if alert.last_error else ""
    return f"{alert.source}: {alert.level.value}, {why}{error}; {_good(alert)}"


def render_health(assessment: HealthAssessment) -> str:
    if not assessment.unwell:
        return f"all {len(assessment.assessed)} source(s) are well (or have not run yet)."
    lines = [f"  {alert_line(a)}" for a in assessment.unwell]
    lines.append("")
    lines.append(f"{len(assessment.unwell)} of {len(assessment.assessed)} source(s) need a look.")
    return "\n".join(lines)


def render_health_json(assessment: HealthAssessment) -> str:
    data = {
        "assessed": list(assessment.assessed),
        "unwell": [
            {
                "source": a.source,
                "health": a.level.value,
                "reasons": list(a.reasons),
                "last_error": a.last_error,
                "last_good": a.last_good.isoformat() if a.last_good else None,
            }
            for a in assessment.unwell
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)
