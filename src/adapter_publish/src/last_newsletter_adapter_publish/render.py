"""Pure rendering of a Digest to text. No I/O, so every publisher shares one definition."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import re
from html import escape
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from datetime import date, time

    from last_newsletter_core.use_cases.list_upcoming_events import (
        UpcomingDay,
        UpcomingEvent,
        UpcomingEvents,
    )
    from ranked_digest.entities import Digest, Theme

MAX_TITLE_CHARS = 140
_NOON = 12
_SPACE = re.compile(r"\s+")
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]<>()#+!|~&])")


def _one_line(text: str, limit: int = MAX_TITLE_CHARS) -> str:
    """Whitespace (including newlines) collapsed, and cut with an ellipsis past `limit`."""
    flat = _SPACE.sub(" ", text).strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "\u2026"


def _md_escape(text: str) -> str:
    return _MD_SPECIAL.sub(r"\\\1", text)


def _safe_url(url: str | None) -> str | None:
    """Only http(s) links are ever emitted; anything else (javascript:, data:, ...) is dropped."""
    if url is None or not url.strip():
        return None
    flat = url.strip()
    if _SPACE.search(flat) or not flat.isprintable():
        return None
    parts = urlsplit(flat)
    return flat if parts.scheme in {"http", "https"} and parts.netloc else None


def _clock(value: time) -> str:
    hour = value.hour % _NOON or _NOON
    return f"{hour}:{value.minute:02d} {'AM' if value.hour < _NOON else 'PM'}"


def _day_label(day: date) -> str:
    return f"{day:%a %b} {day.day}"


def upcoming_when(event: UpcomingEvent) -> str:
    """Human text for when it happens: showtimes, a time range (with the end date when it runs
    past midnight), a single time, or "all day"."""
    if event.all_day or event.start is None:
        return "all day"
    if event.showtimes:
        return ", ".join(_clock(t) for t in event.showtimes)
    if event.end is None:
        return _clock(event.start)
    end = _clock(event.end)
    if event.end_day is not None:
        end = f"{end} {_day_label(event.end_day)}"
    return f"{_clock(event.start)} \u2013 {end}"


def upcoming_where(event: UpcomingEvent) -> str:
    return ", ".join(_one_line(p, 80) for p in (event.venue, event.city) if p.strip())


def upcoming_heading(upcoming: UpcomingEvents) -> str:
    return f"Coming up: {_day_label(upcoming.first_day)} to {_day_label(upcoming.last_day)}"


def _has_upcoming(upcoming: UpcomingEvents | None) -> bool:
    return upcoming is not None and upcoming.event_count > 0


def _markdown_upcoming_line(event: UpcomingEvent) -> str:
    parts = [f"**{_md_escape(_one_line(event.title))}**", upcoming_when(event)]
    where = upcoming_where(event)
    if where:
        parts.append(_md_escape(where))
    line = "- " + " \u2014 ".join(parts)
    if event.mention_count > 1:
        line += f" *(in {event.mention_count} emails)*"
    url = _safe_url(event.url)
    if url is not None:
        line += f" [link](<{url.replace('>', '%3E')}>)"
    return f"{line} <!-- event:{event.event_id} -->"


def _markdown_upcoming(upcoming: UpcomingEvents) -> str:
    blocks = [f"## {upcoming_heading(upcoming)}"]
    for day in upcoming.days:
        lines = [f"### {_day_label(day.day)}", ""]
        lines += [_markdown_upcoming_line(e) for e in day.events]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _markdown_section(theme: Theme) -> str:
    lines = [f"## {theme.title} ({theme.source_count} sources)", "", theme.summary]
    if theme.relevant_until is not None:
        lines += ["", f"*Relevant until {theme.relevant_until.isoformat()}.*"]
    if theme.streak > 1:
        lines += ["", f"*Recurring for {theme.streak} periods in a row.*"]
    return "\n".join(lines)


def render_markdown(digest: Digest, upcoming: UpcomingEvents | None = None) -> str:
    header = (
        f"# {digest.cadence.value.capitalize()} digest: "
        f"{digest.period_start.date().isoformat()} to {digest.period_end.date().isoformat()}"
    )
    summary_line = f"{digest.total_messages} messages from {digest.total_sources} sources."
    coming = f"{_markdown_upcoming(upcoming)}\n\n" if upcoming and _has_upcoming(upcoming) else ""
    if not digest.themes:
        return f"{header}\n\n{summary_line}\n\n{coming}No themes this period.\n"
    sections = "\n\n".join(_markdown_section(theme) for theme in digest.themes)
    return f"{header}\n\n{summary_line}\n\n{coming}{sections}\n"


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


def _html_upcoming_row(event: UpcomingEvent) -> str:
    where = upcoming_where(event)
    pieces = [
        f'<span class="up-title">{escape(_one_line(event.title))}</span>',
        f'<span class="up-when">{escape(upcoming_when(event))}</span>',
    ]
    if where:
        pieces.append(f'<span class="up-where">{escape(where)}</span>')
    if event.mention_count > 1:
        pieces.append(f'<span class="badge badge-streak">in {event.mention_count} emails</span>')
    url = _safe_url(event.url)
    if url is not None:
        href = escape(url, quote=True)
        pieces.append(f'<a class="up-link" href="{href}" rel="noopener noreferrer">link</a>')
    event_id = escape(str(event.event_id), quote=True)
    return f'<li class="up-row" data-event-id="{event_id}">{" ".join(pieces)}</li>'


def _html_upcoming_day(day: UpcomingDay) -> str:
    rows = "".join(_html_upcoming_row(e) for e in day.events)
    label = escape(_day_label(day.day))
    return (
        f'<div class="up-day"><div class="up-date">{label}</div>'
        f'<ul class="up-list">{rows}</ul></div>'
    )


def _html_upcoming(upcoming: UpcomingEvents) -> str:
    days = "".join(_html_upcoming_day(d) for d in upcoming.days)
    return (
        '<div class="card upcoming">'
        f'<div class="card-title">{escape(upcoming_heading(upcoming))}</div>'
        f"{days}</div>"
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
.card-title { overflow-wrap: anywhere; font-size: 15px; font-weight: 600; color: #24292f; }
.badges { display: flex; gap: 6px; flex-wrap: wrap; flex-shrink: 0; }
.badge {
  border-radius: 20px; padding: 2px 10px; font-size: 11px; font-weight: 600;
  background: #f6f8fa; border: 1px solid #d0d7de; color: #57606a; white-space: nowrap;
}
.badge-deadline { background: #ffebe9; color: #cf222e; border-color: #ff8182; }
.badge-streak { background: #ddf4ff; color: #0550ae; border-color: #54aeff; }
.card-summary { color: #57606a; font-size: 13px; margin-top: 10px; }
.card.upcoming { border-left-color: #8250df; }
.up-day { margin-top: 12px; }
.up-date { font-size: 12px; font-weight: 600; color: #57606a; text-transform: uppercase; }
.up-list { list-style: none; margin-top: 4px; }
.up-row { padding: 4px 0; border-top: 1px solid #eaeef2; }
.up-title { font-weight: 600; overflow-wrap: anywhere; }
.up-when, .up-where { color: #57606a; margin-left: 8px; }
.up-link { margin-left: 8px; color: #0969da; font-size: 12px; }
.footer {
  margin-top: 32px; padding-top: 16px; border-top: 1px solid #d0d7de;
  color: #57606a; font-size: 12px; text-align: center;
}
@media (max-width: 600px) {
  body { padding: 12px 8px; }
  .card-top { flex-direction: column; gap: 8px; }
}
"""


def render_html(digest: Digest, upcoming: UpcomingEvents | None = None) -> str:
    """Every value from an email is escaped; no remote content or scripts are emitted. The only
    links are the http(s) URLs of upcoming events, escaped and marked `noopener`."""
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
        f"{_html_upcoming(upcoming) if upcoming and _has_upcoming(upcoming) else ''}"
        f"{sections}"
        '<div class="footer">Generated by last-newsletter</div>'
        "</div></body></html>\n"
    )
