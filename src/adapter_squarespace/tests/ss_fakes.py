"""Builders for Squarespace-shaped items and pages, and `httpx.MockTransport` answers."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

LA = ZoneInfo("America/Los_Angeles")


def ms(year: int, month: int, day: int, hour: int = 20, minute: int = 0) -> int:
    """Epoch milliseconds for a Los Angeles wall-clock time."""
    return int(datetime(year, month, day, hour, minute, tzinfo=LA).timestamp() * 1000)


def para(*lines: str) -> str:
    return "".join(f'<p style="white-space:pre-wrap;">{line}</p>' for line in lines)


def item(
    item_id: str = "abc1",
    title: str = "Thursday, November 12, 2026",
    *,
    start: int | None = None,
    excerpt: str = "",
    tags: list[str] | None = None,
    url_id: str = "thursday-november-12-2026",
    updated: int | None = None,
    body: str = "",
) -> dict[str, object]:
    return {
        "id": item_id,
        "title": title,
        "startDate": ms(2026, 11, 12) if start is None else start,
        "endDate": ms(2026, 11, 12, 22),  # the editor's default length: never trusted
        "fullUrl": f"/events/{url_id}",
        "urlId": url_id,
        "excerpt": excerpt,
        "body": body,
        "tags": tags or [],
        "categories": [],
        "location": {"mapLat": 40.72, "mapLng": -74.0},  # a placeholder on many sites
        "updatedOn": updated if updated is not None else ms(2026, 11, 1, 12),
    }


def page(*upcoming: dict[str, object], past: int = 0) -> dict[str, object]:
    return {
        "website": {},
        "collection": {"title": "Events"},
        "upcoming": list(upcoming),
        "past": [item(f"p{n}") for n in range(past)],
        "pagination": {"nextPage": True},
    }


def served(body: object, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        if isinstance(body, (bytes, str)):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
