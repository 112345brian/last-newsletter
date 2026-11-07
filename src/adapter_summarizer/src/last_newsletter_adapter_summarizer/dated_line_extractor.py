"""A deterministic, model-free `EventExtractor`: every line holding an ISO date (YYYY-MM-DD)
becomes a candidate event whose title is the rest of the line and whose evidence is the line.

Deliberately dumb. It exists so the `process` stage runs end to end with no model, no network
and no spend; ingest still validates each candidate (dates, evidence, past dates). The LLM
extractor plugs in behind the same `EventExtractor` port later.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import re
from typing import TYPE_CHECKING

from last_newsletter_core.events import EventCandidate, EventKind, PartialWhen

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from last_newsletter_core.entities import EmailMessage
    from last_newsletter_core.events import EventCandidate as Candidate

_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MAX_PER_MESSAGE = 50
_SEPARATORS = " \t-|,:;\u2013\u2014"


class NoEmbeddedEvents:
    """`EmbeddedEventReader` that finds nothing, so every message goes to the extractor."""

    def read(self, message: EmailMessage) -> list[Candidate]:
        return []


class DatedLineExtractor:
    def extract(
        self, messages: Sequence[EmailMessage], *, now: datetime, home_tz: str
    ) -> list[Candidate]:
        del now, home_tz  # dates are explicit in the text; ingest resolves and validates them
        found: list[Candidate] = []
        for message in messages:
            count = 0
            for line in message.body_text.splitlines():
                match = _ISO_DATE.search(line)
                if match is None or count >= _MAX_PER_MESSAGE:
                    continue
                evidence = line.strip()
                title = (line[: match.start()] + " " + line[match.end() :]).strip(_SEPARATORS)
                year, month, day = (int(g) for g in match.groups())
                found.append(
                    EventCandidate(
                        message_id=message.message_id,
                        title=" ".join(title.split()),
                        kind=EventKind.EVENT,
                        when=PartialWhen(year=year, month=month, day=day, raw_text=match.group(0)),
                        evidence=evidence,
                    )
                )
                count += 1
        return found
