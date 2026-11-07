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


def _card_class(theme: Theme) -> str:
    """Border color: a theme with a known, close deadline is the most actionable (urgent);
    one that's recurred across periods has earned standing (recurring); anything else is new."""
    if theme.relevant_until is not None:
        return "urgent"
    if theme.streak > 1:
        return "recurring"
    return "new"


def _badges(theme: Theme) -> str:
    # "1 sources" is always true of every extractive-mode theme (one theme per message) and
    # adds nothing even under anthropic, where it's just the common case -- only worth
    # showing once real cross-source merging happened.
    badges = (
        [f'<span class="badge badge-sources">{theme.source_count} sources</span>']
        if theme.source_count > 1
        else []
    )
    if theme.relevant_until is not None:
        badges.append(
            f'<span class="badge badge-deadline">until {theme.relevant_until.isoformat()}</span>'
        )
    if theme.streak > 1:
        badges.append(f'<span class="badge badge-streak">{theme.streak}&times; in a row</span>')
    return "".join(badges)


def _html_section(theme: Theme) -> str:
    return (
        f'<div class="card {_card_class(theme)}">'
        '<div class="card-top">'
        f'<div class="card-title">{escape(theme.title)}</div>'
        f'<div class="badges">{_badges(theme)}</div>'
        "</div>"
        f'<p class="card-summary">{escape(theme.summary)}</p>'
        "</div>"
    )


_HTML_STYLE = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #f6f8fa; color: #24292f;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 14px; line-height: 1.6; padding: 24px 16px;
}
.container { max-width: 700px; margin: 0 auto; }
.header {
  background: #ffffff; border: 1px solid #d0d7de; border-radius: 8px;
  padding: 20px 24px; margin-bottom: 24px;
}
.header h1 { color: #0969da; font-size: 20px; margin-bottom: 8px; }
.header .meta { color: #57606a; font-size: 13px; }
.card {
  background: #ffffff; border: 1px solid #d0d7de; border-radius: 8px;
  padding: 16px 20px; margin-bottom: 12px; border-left: 4px solid #d0d7de;
}
.card.urgent { border-left-color: #cf222e; }
.card.recurring { border-left-color: #0969da; }
.card.new { border-left-color: #1a7f37; }
.card-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.card-title { font-size: 15px; font-weight: 600; color: #24292f; }
.badges { display: flex; gap: 6px; flex-wrap: wrap; flex-shrink: 0; }
.badge {
  border-radius: 20px; padding: 2px 10px; font-size: 11px; font-weight: 600;
  background: #f6f8fa; border: 1px solid #d0d7de; color: #57606a; white-space: nowrap;
}
.badge-deadline { background: #ffebe9; color: #cf222e; border-color: #ff8182; }
.badge-streak { background: #ddf4ff; color: #0550ae; border-color: #54aeff; }
.card-summary { color: #57606a; font-size: 13px; margin-top: 10px; }
.footer {
  margin-top: 32px; padding-top: 16px; border-top: 1px solid #d0d7de;
  color: #57606a; font-size: 12px; text-align: center;
}
@media (max-width: 600px) {
  body { padding: 12px 8px; }
  .card-top { flex-direction: column; gap: 8px; }
}
"""


def render_html(digest: Digest) -> str:
    """Every value from an email is escaped; no remote content, scripts or links are emitted."""
    summary_line = f"{digest.total_messages} messages from {digest.total_sources} sources."
    sections = (
        "".join(_html_section(theme) for theme in digest.themes)
        if digest.themes
        else "<p>No themes this period.</p>"
    )
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<style>{_HTML_STYLE}</style></head><body><div class="container">'
        '<div class="header">'
        f"<h1>{escape(digest_heading(digest))}</h1>"
        f'<div class="meta">{escape(summary_line)}</div>'
        "</div>"
        f"{sections}"
        '<div class="footer">Generated by last-newsletter</div>'
        "</div></body></html>\n"
    )
