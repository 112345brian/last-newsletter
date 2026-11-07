"""The JSON Schema sent as Ollama's `format`, and strict parsing of what comes back."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import json
from dataclasses import dataclass
from typing import Any

from last_newsletter_adapter_events.errors import ModelOutputError

KINDS = ("event", "deadline", "task")
CONFIDENCES = ("low", "medium", "high")

_STR = {"type": "string"}
_STR_LIST = {"type": "array", "items": _STR}

EVENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": _STR,
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "start_text": _STR,
                    "end_text": _STR,
                    "venue": _STR,
                    "city": _STR,
                    "tags": _STR_LIST,
                    "price": _STR,
                    "age": _STR,
                    "organizers": _STR_LIST,
                    "url": _STR,
                    "cancelled": {"type": "boolean"},
                    "confidence": {"type": "string", "enum": list(CONFIDENCES)},
                    "evidence": _STR,
                },
                "required": ["title", "kind", "start_text", "evidence", "cancelled", "confidence"],
            },
        }
    },
    "required": ["events"],
}


@dataclass(frozen=True, slots=True)
class RawEvent:
    """One event as the model reported it: every string is still untrusted."""

    title: str
    kind: str
    start_text: str
    end_text: str
    venue: str
    city: str
    tags: tuple[str, ...]
    price: str
    age: str
    organizers: tuple[str, ...]
    url: str
    cancelled: bool
    confidence: str
    evidence: str


def parse_model_output(text: str) -> list[RawEvent]:
    """Strictly validate the model's text. Raises `ModelOutputError` on any violation."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        msg = "model output is not JSON"
        raise ModelOutputError(msg) from exc
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        msg = "model output lacks an 'events' list"
        raise ModelOutputError(msg)
    return [_raw_event(item) for item in data["events"]]


def _raw_event(item: object) -> RawEvent:
    if not isinstance(item, dict):
        msg = "event is not an object"
        raise ModelOutputError(msg)
    kind = _text(item, "kind", required=True)
    confidence = _text(item, "confidence", required=True)
    if kind not in KINDS or confidence not in CONFIDENCES:
        msg = "event has an out-of-range enum value"
        raise ModelOutputError(msg)
    cancelled = item.get("cancelled")
    if not isinstance(cancelled, bool):
        msg = "'cancelled' must be a boolean"
        raise ModelOutputError(msg)
    return RawEvent(
        title=_text(item, "title", required=True),
        kind=kind,
        start_text=_text(item, "start_text", required=True),
        end_text=_text(item, "end_text"),
        venue=_text(item, "venue"),
        city=_text(item, "city"),
        tags=_texts(item, "tags"),
        price=_text(item, "price"),
        age=_text(item, "age"),
        organizers=_texts(item, "organizers"),
        url=_text(item, "url"),
        cancelled=cancelled,
        confidence=confidence,
        evidence=_text(item, "evidence", required=True),
    )


def _text(item: dict[str, Any], key: str, *, required: bool = False) -> str:
    value = item.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        msg = f"'{key}' must be a string"
        raise ModelOutputError(msg)
    return value


def _texts(item: dict[str, Any], key: str) -> tuple[str, ...]:
    value = item.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        msg = f"'{key}' must be a list of strings"
        raise ModelOutputError(msg)
    return tuple(str(v) for v in value)
