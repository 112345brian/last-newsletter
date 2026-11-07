"""The read side: list stored events with the mentions that cite them and their possible
duplicates. Shows only what the ledger stores (title, date, the evidence quote); never a
message body."""

from __future__ import annotations

__arbor__ = {"ring": "cli"}

import json
from typing import TYPE_CHECKING, Any

from last_newsletter_core.events import AllDay

if TYPE_CHECKING:
    from last_newsletter_core.events import Event, ItemTime


def _when(when: ItemTime) -> str:
    if isinstance(when, AllDay):
        return when.day.isoformat()
    return f"{when.start.isoformat()} [{when.tz_name}]"


def _links(events: list[Event]) -> dict[str, set[str]]:
    """Possible-duplicate links in both directions: a link recorded on one side is still a
    link when you look at the other."""
    links: dict[str, set[str]] = {str(e.id): set() for e in events}
    for e in events:
        for other in e.possible_duplicates:
            links[str(e.id)].add(str(other))
            if str(other) in links:
                links[str(other)].add(str(e.id))
    return links


def events_as_data(events: list[Event]) -> list[dict[str, Any]]:
    titles = {str(e.id): e.title for e in events}
    links = _links(events)
    return [
        {
            "id": str(e.id),
            "kind": e.kind.value,
            "title": e.title,
            "when": _when(e.when),
            "state": e.state.value,
            "first_seen": e.first_seen.isoformat(),
            "last_seen": e.last_seen.isoformat(),
            "mentions": [
                {
                    "message_id": m.message_id,
                    "seen_at": m.seen_at.isoformat(),
                    "rung": m.match_rule.value,
                    "evidence": m.evidence,
                    "cites": str(m.cited_event_id),
                }
                for m in e.mentions
            ],
            "possible_duplicates": [
                {"id": other, "title": titles.get(other, "(not in ledger)")}
                for other in sorted(links[str(e.id)])
            ],
        }
        for e in events
    ]


def render_json(events: list[Event]) -> str:
    return json.dumps(events_as_data(events), indent=2, ensure_ascii=False)


def render_text(events: list[Event]) -> str:
    if not events:
        return "no events stored yet (run `fetch`, then `process`)"
    lines: list[str] = []
    for item in events_as_data(events):
        lines.append(f"{item['id']}  {item['when']}  {item['title']}  [{item['state']}]")
        lines.extend(
            f"    mention {m['message_id']}  rung={m['rung']}  evidence: {m['evidence']}"
            for m in item["mentions"]
        )
        lines.extend(
            f"    possible duplicate of {d['id']}  {d['title']}"
            for d in item["possible_duplicates"]
        )
    return "\n".join(lines)
