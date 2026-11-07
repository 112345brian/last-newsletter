from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from last_newsletter_adapter_events import OllamaClient, OllamaConfig
from last_newsletter_core.entities import EmailMessage

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


class ScriptedTransport:
    """Each call pops the next step: bytes (200 body), (status, bytes), or an exception."""

    def __init__(self, *steps: object) -> None:
        self.steps = list(steps)
        self.requests: list[dict[str, Any]] = []

    def post(self, url: str, body: bytes, *, timeout_s: float) -> tuple[int, bytes]:
        self.requests.append({"url": url, "body": json.loads(body), "timeout": timeout_s})
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, BaseException):
            raise step
        if isinstance(step, tuple):
            return step
        assert isinstance(step, bytes)
        return 200, step


def envelope(content: str) -> bytes:
    return json.dumps({"message": {"role": "assistant", "content": content}}).encode()


def answer(*events: dict[str, Any]) -> bytes:
    return envelope(json.dumps({"events": list(events)}))


def event(**kw: object) -> dict[str, Any]:
    base = {
        "title": "Moon Party",
        "kind": "event",
        "start_text": "Sat Dec 12, 9pm",
        "end_text": "",
        "cancelled": False,
        "confidence": "high",
        "evidence": "Moon Party Sat Dec 12, 9pm",
    }
    return {**base, **kw}


def client_for(
    transport: ScriptedTransport, *, max_retries: int = 2, think: bool | None = None
) -> OllamaClient:
    config = OllamaConfig(model="m", max_retries=max_retries, think=think)
    return OllamaClient(config, transport=transport, sleep=_no_sleep)


def _no_sleep(_s: float) -> None:
    return None


def msg(body: str, *, subject: str = "Weekend", message_id: str = "m1") -> EmailMessage:
    return EmailMessage(
        message_id=message_id,
        sender="a@b.c",
        subject=subject,
        received_at=NOW,
        body_text=body,
    )
