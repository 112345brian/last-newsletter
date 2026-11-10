"""Small helpers the venue modules share."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import html
import re
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from last_newsletter_core.events import EventCandidate

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def clean(value: object) -> str:
    """Text with entities decoded, control characters and runs of whitespace collapsed."""
    if value is None or isinstance(value, (dict, list, bool)):
        return ""
    return _SPACE.sub(" ", _CONTROL.sub(" ", html.unescape(str(value)))).strip()


def plain(markup: object) -> str:
    """Visible text from an HTML fragment."""
    if not isinstance(markup, str):
        return ""
    return clean(_TAGS.sub(" ", markup))


def day_of(candidate: EventCandidate) -> date:
    when = candidate.when
    if when is None or when.year is None or when.month is None or when.day is None:
        return date.min
    return date(when.year, when.month, when.day)
