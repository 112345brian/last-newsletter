"""Concrete Summarizer with no model and no network: one theme per message.

The title is the subject; the summary is the start of the message's own text with links,
control characters and "view in browser / unsubscribe" lines removed. Nothing is invented, so
every line a reader sees came from the email it cites. A model-backed summarizer can replace
this behind the same port without any other change.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import re
import unicodedata
from typing import TYPE_CHECKING

from ranked_digest.entities import Theme

if TYPE_CHECKING:
    from datetime import date

    from ranked_digest.entities import EmailMessage

EXCERPT_LIMIT = 400
_NO_SUBJECT = "(no subject)"
_NO_TEXT = "(no text)"
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_BOILERPLATE = re.compile(
    r"unsubscribe|view (?:this )?(?:email )?in (?:your )?browser|manage (?:your )?preferences",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    """Drop control and format characters (NUL, bell, zero-width, bidi marks) but keep spaces."""
    kept = (
        ch for ch in text if ch in "\n\t " or unicodedata.category(ch) not in {"Cc", "Cf", "Cs"}
    )
    return "".join(kept)


def _excerpt(body: str) -> str:
    lines = (_URL.sub(" ", line) for line in _clean(body).splitlines())
    kept = (line for line in lines if not _BOILERPLATE.search(line))
    text = " ".join(" ".join(kept).split())
    if not text:
        return _NO_TEXT
    if len(text) <= EXCERPT_LIMIT:
        return text
    cut = text[:EXCERPT_LIMIT]
    boundary = cut.rfind(" ")
    return (cut[:boundary] if boundary > 0 else cut) + "…"


def _title(subject: str) -> str:
    return " ".join(_clean(subject).split()) or _NO_SUBJECT


class ExtractiveSummarizer:
    """Implements ranked_digest.ports.Summarizer."""

    def summarize(
        self, messages: list[EmailMessage], *, prior_themes: list[Theme], today: date
    ) -> list[Theme]:
        # No continuity: this summarizer does not decide that two messages are "the same
        # topic", so prior themes are deliberately not carried forward.
        return [
            Theme(
                title=_title(message.subject),
                summary=_excerpt(message.body_text),
                source_count=1,
                source_message_ids=(message.message_id,),
            )
            for message in messages
        ]
