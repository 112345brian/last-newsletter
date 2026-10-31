"""Enterprise business rules: plain data, no I/O, no framework types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime


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
    """A topic covered by one or more source emails this period, or carried
    forward from a prior one.

    Importance isn't just "how many sources mentioned it this period" —
    two kinds of theme legitimately outlast a single digest window:

    - A theme with a known future date (a conference, a deadline) matters
      more as that date approaches, with or without a fresh mention. The
      Summarizer sets `relevant_until` when it can extract one; the use
      case keeps the theme in the digest and ranks it by proximity to that
      date until it passes.
    - A theme that keeps recurring across periods (an ongoing saga) earns
      standing from that recurrence. `theme_key` is how the Summarizer
      tells the use case "this is the same theme as last period's X", and
      `streak` is how many consecutive periods it's been seen in a row
      (including this one).

    `personal_weight` is a third, generic signal: the sum of whatever
    `RelevanceWeigher`s are configured (zero by default — see
    BuildDigestUseCase), each translating some personal signal (a knowledge
    base, a listening history, anything) into a number. It's a float, not a
    bool, so one weigher can express "a little relevant" vs "a lot" without
    core caring what produced it or what it means.
    """

    title: str
    summary: str
    source_count: int
    source_message_ids: tuple[str, ...] = field(default_factory=tuple)
    theme_key: str | None = None
    relevant_until: date | None = None
    first_seen: date | None = None
    streak: int = 1
    carried_forward: bool = False
    personal_weight: float = 0.0


@dataclass(frozen=True, slots=True)
class Digest:
    """The finished briefing for one period: themes ranked by how many sources covered them."""

    period_start: datetime
    period_end: datetime
    cadence: Cadence
    themes: tuple[Theme, ...]
    total_messages: int
    total_sources: int


def digest_slug(digest: Digest) -> str:
    """The canonical identity a Digest is referred to by: a timestamped, cadence-tagged
    filesystem-safe name. One definition shared by every adapter that names a Digest on disk
    (JSON storage, Markdown rendering, ...) — a naming scheme is a rule about the domain, not
    a detail that gets to differ per output format."""
    return f"{digest.period_start:%Y-%m-%dT%H%M%S}_{digest.cadence.value}"
