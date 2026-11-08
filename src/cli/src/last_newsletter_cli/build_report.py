"""What `build` tells the owner: the window it considered, what it found, what it wrote, and
why a run that changed nothing new did so. Pure text from facts `main` gathers; no I/O."""

from __future__ import annotations

__arbor__ = {"ring": "cli"}

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from ranked_digest.entities import Digest

_FORCE_HELP = (
    "`--force` ends the window at this moment instead of at midnight UTC, so mail received "
    "today is included; it is a different period, meant for checking the pipeline during setup"
)


@dataclass(frozen=True, slots=True)
class BuildFacts:
    slug: str
    replaced: bool  # a digest for this same window already existed and was overwritten
    force: bool
    raw_total: int  # messages in the raw store
    raw_newest: datetime | None  # received_at of the newest one
    output_dir: str


def _stamp(moment: datetime) -> str:
    return f"{moment:%Y-%m-%d %H:%M} UTC"


def describe_build(digest: Digest, facts: BuildFacts) -> list[str]:
    window = f"{_stamp(digest.period_start)} -> {_stamp(digest.period_end)}"
    mode = "; --force: ends at this moment" if facts.force else ", midnight-aligned"
    found = (
        f"found: {digest.total_messages} message(s) from {digest.total_sources} source(s), "
        f"{len(digest.themes)} theme(s)"
    )
    lines = [f"window: {window} ({digest.cadence.value}{mode})", found]
    if digest.total_messages == 0:
        lines.append(_why_empty(digest, facts))
    verb = "replaced the earlier digest for this window" if facts.replaced else "wrote"
    lines.append(f"{verb}: {facts.output_dir}/{facts.slug}.md")
    if facts.replaced:
        lines.append(
            "no new period: the window is aligned to midnight UTC, so a re-run in the same "
            f"{digest.cadence.value} period rebuilds the same digest in place. {_FORCE_HELP}."
        )
    elif facts.force:
        lines.append(f"{_FORCE_HELP}.")
    return lines


def _why_empty(digest: Digest, facts: BuildFacts) -> str:
    if facts.raw_total == 0:
        return "nothing to summarize: the raw store is empty; run `fetch` first"
    newest = _stamp(facts.raw_newest) if facts.raw_newest is not None else "unknown"
    return (
        "nothing to summarize: no raw message was received inside the window "
        f"(the raw store holds {facts.raw_total} message(s), newest received {newest}); "
        "run `fetch` for newer mail"
        + ("" if facts.force else ", or `--force` to include today's mail")
        + f" (window ends {_stamp(digest.period_end)})"
    )
