"""Concrete EmailSource: connects to a mailbox over IMAP and maps messages to core entities.

Credentials live in environment variables, never in code or config committed to the repo.
Implementation (IMAP fetch + MIME parsing) is intentionally not written yet — this is
scaffolding that locks in the port signature and where the real I/O will live.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from last_newsletter_core.entities import EmailMessage


@dataclass(frozen=True, slots=True)
class ImapConfig:
    host: str
    username: str
    password: str
    mailbox: str = "INBOX"


class ImapEmailSource:
    """Implements last_newsletter_core.ports.EmailSource."""

    def __init__(self, config: ImapConfig) -> None:
        self._config = config

    def fetch_since(self, since: datetime) -> list[EmailMessage]:
        msg = "IMAP fetch not yet implemented"
        raise NotImplementedError(msg)
