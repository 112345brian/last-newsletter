"""Text and JSON for a run and for the per-source status table."""

from __future__ import annotations

__arbor__ = {"ring": "app"}

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from concert_tracker_core.source_runs import (
    HISTORY_WINDOW,
    HealthLevel,
    SourceHealth,
    SourceOutcome,
    judge_health,
)

if TYPE_CHECKING:
    from pathlib import Path

    from concert_tracker_app.run_sources import RunHistory, RunReport, SourceResult
    from concert_tracker_core.source_runs import SourceCatalog


def _result_line(result: SourceResult) -> str:
    o, h = result.outcome, result.health
    if o.errored:
        body = f"{o.status.value}: {o.error}"
    else:
        body = f"{o.found} event(s), {o.created} new, {o.mentioned} new mentions"
    note = f"  [{h.level.value}: {'; '.join(h.reasons)}]" if h.reasons else ""
    return f"  {o.source:<16} {body}  ({o.seconds:.1f}s){note}"


def render_run(report: RunReport) -> str:
    lines = [_result_line(r) for r in report.results]
    lines.append("")
    lines.append(
        f"{len(report.results)} source(s): {report.found} event(s) found, {report.failed} failed."
    )
    unwell = [r.outcome.source for r in report.results if r.health.level in _UNWELL]
    if unwell:
        lines.append(f"Needs a look: {', '.join(unwell)} (see `concert-tracker sources`).")
    return "\n".join(lines)


_UNWELL = (HealthLevel.DEGRADED, HealthLevel.FAILING)


def run_as_data(report: RunReport) -> dict[str, object]:
    return {
        "found": report.found,
        "failed": report.failed,
        "sources": [_outcome_data(r.outcome, r.health) for r in report.results],
    }


def _outcome_data(outcome: SourceOutcome, health: SourceHealth) -> dict[str, object]:
    return {
        "source": outcome.source,
        "status": outcome.status.value,
        "started_at": outcome.started_at.isoformat(),
        "seconds": round(outcome.seconds, 3),
        "found": outcome.found,
        "created": outcome.created,
        "mentioned": outcome.mentioned,
        "error": outcome.error,
        "health": health.level.value,
        "health_reasons": list(health.reasons),
    }


def render_run_json(report: RunReport) -> str:
    return json.dumps(run_as_data(report), indent=2, ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class SourceStatus:
    name: str
    enabled: bool
    last: SourceOutcome | None
    health: SourceHealth


def source_statuses(catalog: SourceCatalog, history: RunHistory | None) -> list[SourceStatus]:
    """Every catalog source with its last outcome and health; never-run ones say so."""
    rows: list[SourceStatus] = []
    for spec in catalog.specs:
        recent = history.recent(spec.name, HISTORY_WINDOW + 1) if history is not None else []
        if recent:
            rows.append(
                SourceStatus(
                    spec.name, spec.enabled, recent[0], judge_health(recent[0], recent[1:])
                )
            )
        else:
            rows.append(SourceStatus(spec.name, spec.enabled, None, SourceHealth(HealthLevel.NEW)))
    return rows


def render_source_statuses(rows: list[SourceStatus], owner_file: Path) -> str:
    lines = []
    for row in rows:
        if row.last is None:
            what = "never run"
        elif row.last.errored:
            what = f"{row.last.status.value}: {row.last.error}"
        else:
            when = row.last.started_at.strftime("%Y-%m-%d %H:%M")
            what = f"{row.last.found} event(s) on {when}"
        off = "  (disabled)" if not row.enabled else ""
        reasons = f"  [{'; '.join(row.health.reasons)}]" if row.health.reasons else ""
        lines.append(f"  {row.name:<16} {row.health.level.value:<9} {what}{reasons}{off}")
    lines.append("")
    lines.append(f"Add, retune or switch off sources in {owner_file}.")
    return "\n".join(lines)
