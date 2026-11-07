"""Cheap pre-filter: mail with no date-like signal never reaches the model."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import re

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_DAY = r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day|sday|nesday|rsday|urday)?"
_SIGNALS = (
    re.compile(rf"\b{_MONTH}\.?\s+\d{{1,2}}\b", re.IGNORECASE),
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(rf"\b{_DAY}\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b", re.IGNORECASE),
    re.compile(r"\b(?:tonight|tomorrow|this weekend|doors)\b", re.IGNORECASE),
)


def has_date_signal(subject: str, body: str) -> bool:
    """True when subject or body mentions anything date- or time-like."""
    haystack = f"{subject}\n{body}"
    return any(pattern.search(haystack) for pattern in _SIGNALS)
