"""Pure rendering of a Digest to text. No I/O, so every publisher shares one definition."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from last_newsletter_core.entities import Digest, Theme


def _markdown_section(theme: Theme) -> str:
    lines = [f"## {theme.title} ({theme.source_count} sources)", "", theme.summary]
    if theme.relevant_until is not None:
        lines += ["", f"*Relevant until {theme.relevant_until.isoformat()}.*"]
    if theme.streak > 1:
        lines += ["", f"*Recurring for {theme.streak} periods in a row.*"]
    return "\n".join(lines)


def render_markdown(digest: Digest) -> str:
    header = (
        f"# {digest.cadence.value.capitalize()} digest: "
        f"{digest.period_start.date().isoformat()} to {digest.period_end.date().isoformat()}"
    )
    summary_line = f"{digest.total_messages} messages from {digest.total_sources} sources."
    if not digest.themes:
        return f"{header}\n\n{summary_line}\n\nNo themes this period.\n"
    sections = "\n\n".join(_markdown_section(theme) for theme in digest.themes)
    return f"{header}\n\n{summary_line}\n\n{sections}\n"


def digest_heading(digest: Digest) -> str:
    return (
        f"{digest.cadence.value.capitalize()} digest: "
        f"{digest.period_start.date().isoformat()} to {digest.period_end.date().isoformat()}"
    )


def _html_section(theme: Theme) -> str:
    parts = [
        f"<h2>{escape(theme.title)} <small>({theme.source_count} sources)</small></h2>",
        f"<p>{escape(theme.summary)}</p>",
    ]
    if theme.relevant_until is not None:
        parts.append(f"<p><em>Relevant until {theme.relevant_until.isoformat()}.</em></p>")
    if theme.streak > 1:
        parts.append(f"<p><em>Recurring for {theme.streak} periods in a row.</em></p>")
    return "\n".join(parts)


def render_html(digest: Digest) -> str:
    """Every value from an email is escaped; no remote content, scripts or links are emitted."""
    summary_line = f"{digest.total_messages} messages from {digest.total_sources} sources."
    sections = (
        "\n".join(_html_section(theme) for theme in digest.themes)
        if digest.themes
        else "<p>No themes this period.</p>"
    )
    return (
        "<!doctype html><html><body>"
        f"<h1>{escape(digest_heading(digest))}</h1>"
        f"<p>{escape(summary_line)}</p>"
        f"{sections}"
        "</body></html>\n"
    )
