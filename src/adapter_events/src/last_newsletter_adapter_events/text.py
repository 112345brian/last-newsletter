"""Turn an email into the bounded plain text the model sees (and the guard checks against)."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import re
from html import unescape

MAX_BODY_CHARS = 12_000
_TAG_LOOKS = re.compile(r"</?[a-zA-Z][^>]*>")
_DROPPED = re.compile(r"<(script|style|head)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_BREAKS = re.compile(r"</?(?:p|div|br|li|tr|h[1-6]|table|section)\b[^>]*>", re.IGNORECASE)
_LINK = re.compile(r"<a\b[^>]*?href=[\"']?(https?://[^\s\"'>]+)[^>]*>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]*>")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANKS = re.compile(r"[ \t\xa0]+")
_NEWLINES = re.compile(r"\n\s*\n+")


def clean_text(raw: str, *, limit: int = MAX_BODY_CHARS) -> str:
    """Strip HTML if present, drop control characters (NUL...), collapse blanks, cap length."""
    text = raw
    if _TAG_LOOKS.search(text):
        text = _DROPPED.sub(" ", text)
        text = _BREAKS.sub("\n", text)
        text = _LINK.sub(r" [\1] ", text)
        text = _TAGS.sub("", text)
    text = unescape(text)
    text = _CONTROL.sub("", text)
    text = "\n".join(_BLANKS.sub(" ", line).strip() for line in text.splitlines())
    text = _NEWLINES.sub("\n\n", text).strip()
    return text[:limit]


def squash(text: str) -> str:
    """Whitespace-insensitive form used for substring checks."""
    return " ".join(text.split())
