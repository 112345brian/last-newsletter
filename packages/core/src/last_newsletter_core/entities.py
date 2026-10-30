"""Enterprise business rules: plain data, no I/O, no framework types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """A single email as ingested from any source (IMAP, Gmail API, manual forward)."""

    message_id: str
    sender: str
    subject: str
    received_at: datetime
    body_text: str
    source_label: str = ""


class Cadence(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


@dataclass(frozen=True, slots=True)
class Theme:
    """A topic that recurs across one or more source emails, ranked by coverage."""

    title: str
    summary: str
    source_count: int
    source_message_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Digest:
    """The finished briefing for one period: themes ranked by how many sources covered them."""

    period_start: datetime
    period_end: datetime
    cadence: Cadence
    themes: tuple[Theme, ...]
    total_messages: int
    total_sources: int
