"""Decode RFC 2047 headers and extract readable text from a `email.message.Message`.

No IMAP, no POP, no newsletter, no app-specific concept anywhere in this module — just the two
things almost anything reading parsed email ends up needing: a header value as one properly
decoded string (not raw encoded-words), and a body as plain text (preferring an actual
text/plain part, falling back to converting text/html when that's all there is).
"""

from __future__ import annotations

__arbor__ = {"ring": "libs"}

from email.header import decode_header
from typing import TYPE_CHECKING

import html2text

if TYPE_CHECKING:
    from email.message import Message

__all__ = ["decode_header_value", "extract_body_text"]

_html_converter = html2text.HTML2Text()
_html_converter.ignore_images = True
_html_converter.ignore_tables = False


def decode_header_value(raw: str | None) -> str:
    """A header's value as one decoded string, joining every RFC 2047 encoded-word run.
    `raw` is typically `msg.get("Subject")`/`msg.get("From")` etc. — `None` (header absent)
    returns an empty string."""
    if not bool(raw):
        return ""
    chunks: list[str] = []
    for part, charset in decode_header(raw):
        chunks.append(
            part.decode(charset or "utf-8", errors="replace")
            if isinstance(part, bytes)
            else str(part)
        )
    return "".join(chunks)


def extract_body_text(msg: Message) -> str:
    """The message's body as plain text: the first `text/plain` part found, or the first
    `text/html` part converted to text if there's no plain-text part at all. Attachments are
    skipped. Returns an empty string if neither is present."""
    plain: str | None = None
    html: str | None = None
    for part in msg.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        charset = part.get_content_charset() or "utf-8"
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        decoded = payload.decode(charset, errors="replace")
        if part.get_content_type() == "text/plain" and plain is None:
            plain = decoded
        elif part.get_content_type() == "text/html" and html is None:
            html = decoded
    if plain is not None:
        return plain.strip()
    if html is not None:
        return _html_converter.handle(html).strip()
    return ""
