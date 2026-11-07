"""Pure ntfy policy: how a push is built, which failures spool, and how a spool is flushed.

No environment, files, clock or logging: the caller passes the server, topic and token it resolved, the ``now`` it
read, and the function that actually re-sends. The caller keeps the glue (reading config, persisting the spool,
logging).
"""
from __future__ import annotations

__arbor__ = {"ring": "core"}

import json
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

#: A failed high/urgent push is spooled and re-sent by the next successful push; bounded so a long outage
#: does not flood the phone when the server comes back.
SPOOL_MAX = 20
SPOOL_MAX_AGE_H = 24

#: Only these priorities are worth redelivering.
SPOOLED_PRIORITIES = frozenset({"high", "urgent", "max"})

#: ntfy's string priorities on the integer scale of its JSON publish API.
PRIORITY_INT: Mapping[str, int] = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5, "max": 5}

#: ntfy caps action buttons at three per notification.
MAX_ACTIONS = 3

SpoolEntry = Mapping[str, object]


def ascii_safe(text: str) -> str:
    """*text* with non-ASCII characters replaced by ``?`` (header values and console logs must be ASCII-safe)."""
    return text.encode("ascii", "replace").decode("ascii")


def should_spool(priority: str) -> bool:
    """Whether a push that failed at *priority* is queued for redelivery."""
    return priority in SPOOLED_PRIORITIES


def bound_spool(entries: Sequence[SpoolEntry]) -> list[SpoolEntry]:
    """The newest ``SPOOL_MAX`` entries."""
    return list(entries[-SPOOL_MAX:])


def spool_entry(
    *,
    now: datetime,
    title: str,
    body: str,
    priority: str,
    tags: str,
    click: str | None,
    actions: Sequence[Mapping[str, object]] | None,
) -> dict[str, object]:
    """The record queued for a failed push, stamped with *now*."""
    return {
        "ts": now.isoformat(timespec="seconds"),
        "title": title, "body": body, "priority": priority,
        "tags": tags, "click": click, "actions": actions,
    }


def build_publish_request(
    *,
    server: str,
    topic: str,
    token: str,
    title: str,
    body: str,
    priority: str,
    tags: str,
    click: str | None,
    actions: Sequence[Mapping[str, object]] | None,
) -> urllib.request.Request:
    """The POST for one push. With *actions* it is ntfy's JSON publish API (action definitions do not fit in
    headers); otherwise a plain body with header controls. *token* is the bearer token of an auth-protected server,
    empty for a public one."""
    auth = {"Authorization": f"Bearer {token}"} if token else {}
    if actions:
        payload: dict[str, object] = {
            "topic": topic,
            "title": title,  # JSON transport is UTF-8 -- keep emoji/stars intact
            "message": body,
            "priority": PRIORITY_INT.get(priority, 3),
            "actions": list(actions[:MAX_ACTIONS]),
        }
        if tags:
            payload["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        if click:
            payload["click"] = click
        return urllib.request.Request(
            server,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **auth},
            method="POST",
        )
    headers = {
        # ntfy controls live in headers; keep header values ASCII-safe.
        "Title": ascii_safe(title),
        "Priority": priority,
        **auth,
    }
    if tags:
        headers["Tags"] = tags
    if click:
        headers["Click"] = click
    return urllib.request.Request(
        f"{server}/{topic}",
        data=body.encode("utf-8"),
        headers=headers,
        method="POST",
    )


@dataclass(frozen=True)
class PendingPush:
    """One spooled push, ready to be sent again."""

    title: str
    body: str
    priority: str
    tags: str
    click: str | None
    actions: list[dict[str, object]] | None


def _text(value: object, default: str) -> str:
    return value if isinstance(value, str) else default


def pending_push(entry: Mapping[str, object]) -> PendingPush:
    """The push a spooled *entry* describes, with the ``[delayed]`` prefix and defaults for missing fields."""
    click = entry.get("click")
    actions = entry.get("actions")
    return PendingPush(
        title=f"[delayed] {_text(entry.get('title'), '')}",
        body=_text(entry.get("body"), ""),
        priority=_text(entry.get("priority"), "default"),
        tags=_text(entry.get("tags"), ""),
        click=click if isinstance(click, str) else None,
        actions=[dict(a) for a in actions if isinstance(a, Mapping)] if isinstance(actions, list) else None,
    )


def _is_fresh(entry: Mapping[str, object], cutoff: datetime) -> bool:
    try:
        return datetime.fromisoformat(_text(entry.get("ts"), "")) >= cutoff
    except (ValueError, TypeError):
        return False


def flush_spool(
    entries: Sequence[SpoolEntry],
    *,
    now: datetime,
    resend: Callable[[PendingPush], bool],
) -> list[SpoolEntry]:
    """Re-send *entries* oldest first and return those to keep spooled.

    An entry older than ``SPOOL_MAX_AGE_H`` hours (or with an unreadable timestamp) is dropped. The first *resend*
    that returns False means the server flapped mid-flush: that entry and every later one are kept for next time.
    """
    cutoff = now - timedelta(hours=SPOOL_MAX_AGE_H)
    for i, entry in enumerate(entries):
        if not _is_fresh(entry, cutoff):
            continue
        if not resend(pending_push(entry)):
            return list(entries[i:])
    return []
