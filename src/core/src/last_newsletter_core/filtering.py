"""Pure rule for recognizing a message as noise rather than a newsletter.

`FilterRule.matches` is the one predicate every filtering adapter (and any future one) shares:
true means drop the message. A rule is deliberately conjunctive, not a loose keyword search --
when both `sender_domains` and `subject_phrases` are set, a message must match the sender AND
the subject, so a genuine newsletter that happens to mention a filtered phrase in passing is
not caught by sender alone. At least one of the two must be set; a rule with neither would
either match everything or nothing, and both are bugs worth raising on construction rather
than discovering silently later.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ranked_digest.entities import EmailMessage


def _sender_domain(sender: str) -> str:
    return sender.rsplit("@", 1)[-1].strip("> \t").lower()


@dataclass(frozen=True, slots=True)
class FilterRule:
    """`name` identifies the rule in tests and logs; it plays no part in matching."""

    name: str
    sender_domains: tuple[str, ...] = ()
    subject_phrases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.sender_domains and not self.subject_phrases:
            msg = f"filter rule {self.name!r} must set sender_domains, subject_phrases, or both"
            raise ValueError(msg)

    def matches(self, message: EmailMessage) -> bool:
        if self.sender_domains and _sender_domain(message.sender) not in self.sender_domains:
            return False
        if self.subject_phrases:
            subject = message.subject.casefold()
            return any(phrase.casefold() in subject for phrase in self.subject_phrases)
        return True
