"""Optional cloud escalation seam. OFF by default; no real implementation ships here, so no
API key is wired anywhere. The CLI may supply one later behind an explicit flag."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from last_newsletter_adapter_events.errors import EscalationError

if TYPE_CHECKING:
    from last_newsletter_adapter_events.schema import RawEvent


class Escalator(Protocol):
    """Second opinion for one email whose local result was low-confidence or invalid.

    Receives the already-cleaned text (never raw HTML). Its output goes through the same
    parsing and evidence guard as the local model's. Raise `EscalationError` on failure: the
    extractor absorbs it and keeps the local result.
    """

    def escalate(self, *, message_id: str, subject: str, text: str) -> list[RawEvent]: ...


@dataclass
class FakeEscalator:
    """Test double: returns a scripted answer and records its calls."""

    answer: list[RawEvent] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    fail: bool = False

    def escalate(self, *, message_id: str, subject: str, text: str) -> list[RawEvent]:
        self.calls.append(message_id)
        if self.fail:
            msg = "escalator down"
            raise EscalationError(msg)
        return list(self.answer)
