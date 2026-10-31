"""Concrete DigestPublisher: renders a Digest to a Markdown file on disk.

Simplest possible output format to start; an HTML-email or static-feed publisher
can be added later as its own adapter package without touching core or this one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from last_newsletter_core.entities import Digest, Theme


def _slug_for(digest: Digest) -> str:
    return f"{digest.period_start:%Y-%m-%dT%H%M%S}_{digest.cadence.value}"


def _theme_section(theme: Theme) -> str:
    lines = [f"## {theme.title} ({theme.source_count} sources)", "", theme.summary]
    if theme.relevant_until is not None:
        lines += ["", f"*Relevant until {theme.relevant_until.isoformat()}.*"]
    if theme.streak > 1:
        lines += ["", f"*Recurring for {theme.streak} periods in a row.*"]
    return "\n".join(lines)


def _render(digest: Digest) -> str:
    header = (
        f"# {digest.cadence.value.capitalize()} digest: "
        f"{digest.period_start.date().isoformat()} to {digest.period_end.date().isoformat()}"
    )
    summary_line = f"{digest.total_messages} messages from {digest.total_sources} sources."
    if not digest.themes:
        return f"{header}\n\n{summary_line}\n\nNo themes this period.\n"
    sections = "\n\n".join(_theme_section(theme) for theme in digest.themes)
    return f"{header}\n\n{summary_line}\n\n{sections}\n"


class MarkdownPublisher:
    """Implements last_newsletter_core.ports.DigestPublisher."""

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def publish(self, digest: Digest) -> None:
        path = self._output_dir / f"{_slug_for(digest)}.md"
        path.write_text(_render(digest))
