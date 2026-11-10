"""The unit an event is read from: one document that cited it.

A document is whatever a source hands over to be turned into events: an email, a ticketing-API
record, one entry of a calendar feed, a venue's listing page. Core knows only these six facts
about it, so it never needs to know what kind of thing it came from. Mail lives in another
project, which maps its own message type onto this one.

`message_id` is a historical name kept because it is a column in the stored ledger: read it as
"the id of the document that cited the event".
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class SourceDocument:
    message_id: str
    sender: str
    subject: str
    received_at: datetime
    body_text: str
    source_label: str = ""
