"""Application business rule: fetch -> summarize -> publish, orchestrated against ports only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from last_newsletter_core.entities import Cadence, Digest

if TYPE_CHECKING:
    from datetime import datetime

    from last_newsletter_core.ports import DigestPublisher, EmailSource, Summarizer


@dataclass(frozen=True, slots=True)
class BuildDigestRequest:
    since: datetime
    until: datetime
    cadence: Cadence


class BuildDigestUseCase:
    """Takes concrete port implementations at construction time (dependency injection);
    never imports adapter packages directly."""

    def __init__(
        self,
        email_source: EmailSource,
        summarizer: Summarizer,
        publisher: DigestPublisher,
    ) -> None:
        self._email_source = email_source
        self._summarizer = summarizer
        self._publisher = publisher

    def execute(self, request: BuildDigestRequest) -> Digest:
        messages = self._email_source.fetch_since(request.since)
        themes = self._summarizer.summarize(messages)
        ranked = tuple(sorted(themes, key=lambda t: t.source_count, reverse=True))
        sources = {m.source_label for m in messages if m.source_label}

        digest = Digest(
            period_start=request.since,
            period_end=request.until,
            cadence=request.cadence,
            themes=ranked,
            total_messages=len(messages),
            total_sources=len(sources),
        )
        self._publisher.publish(digest)
        return digest
