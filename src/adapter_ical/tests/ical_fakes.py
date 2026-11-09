"""Builders for small synthetic calendars, and `httpx.MockTransport` answers."""

from __future__ import annotations

import httpx
from icalendar import Calendar, Component


def calendar_text(*events: list[str], name: str = "Test feed") -> str:
    """A VCALENDAR holding one VEVENT per list of property lines."""
    body = [f"X-WR-CALNAME:{name}"]
    for lines in events:
        body += ["BEGIN:VEVENT", *lines, "END:VEVENT"]
    return "\r\n".join(
        ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//EN", *body, "END:VCALENDAR", ""]
    )


def vevent(lines: list[str]) -> Component:
    (event,) = Calendar.from_ical(calendar_text(lines)).walk("VEVENT")
    return event


def served(text: str, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(status, text=text, headers={"content-type": "text/calendar"})

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
