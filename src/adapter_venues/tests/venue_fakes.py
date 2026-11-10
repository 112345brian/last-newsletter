"""Builders for venue-shaped payloads, and `httpx.MockTransport` answers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable


def served(body: object, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        if isinstance(body, (bytes, str)):
            return httpx.Response(status, content=body, headers=headers)
        return httpx.Response(status, json=body, headers=headers)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


@dataclass
class Handled:
    """Answers each request by calling `handler` with the decoded query parameters."""

    handler: Callable[[dict[str, str]], httpx.Response]
    queries: list[dict[str, str]] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.queries.append(params)
        return self.handler(params)

    @property
    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self), follow_redirects=True)


def post(title: str, **extra: object) -> dict[str, object]:
    """A WordPress post record the way ACF returns a related artist or venue."""
    return {"ID": 1, "post_title": title, "post_type": "artists", **extra}


def show(
    show_id: int = 101,
    *,
    title: str = "Mdou Moctar",
    when: str = "11/20/2026 8:00 pm",
    headliners: list[str] | None = None,
    supports: list[str] | None = None,
    **acf: object,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "date_and_time_of_show": when,
        "door_time": "7:00 pm",
        "headliner": [post(n) for n in (headliners or [title])],
        "additional_artists": [[post(n)] for n in supports] if supports is not None else "",
        "venue": post("Lodge Room", post_type="venue"),
        "ages": {"value": "allAges", "label": "ALL AGES"},
        "genre": "",
        "show_description": "<div><p>An evening of <b>desert blues</b>.</p></div>",
        "external_ticket_button_url": "",
        "rsvp_url": "",
        "public_tags": False,
    } | acf
    return {
        "id": show_id,
        "link": f"https://www.lodgeroomhlp.com/shows/show-{show_id}/",
        "title": {"rendered": title},
        "modified_gmt": "2026-11-04T22:23:09",
        "acf": fields,
    }
