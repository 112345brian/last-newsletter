"""Application business rule: fetch -> summarize (with continuity) -> weigh -> rank -> publish
-> persist.

Ranking is deterministic and lives here, not in the Summarizer, because it's
mechanical policy, not semantic judgment: a theme with an unexpired
`relevant_until` ranks by proximity to that date (soonest first); everything
else ranks by `source_count + (streak - 1) + personal_weight`, so a theme
that's recurred across periods, or that a configured RelevanceWeigher scored
highly, outranks an equally-covered one-off. Deciding *which* themes exist
(new ones, which prior ones carry forward) is the Summarizer's judgment;
deciding *how much* a theme matters to this specific reader is each
RelevanceWeigher's judgment (zero configured is the default — the generic
program has no personalization opinion at all). This module only combines
whatever those adapters hand back.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from last_newsletter_core.entities import Digest

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime

    from last_newsletter_core.entities import Cadence, Theme
    from last_newsletter_core.ports import (
        DigestPublisher,
        DigestRepository,
        EmailSource,
        RelevanceWeigher,
        Summarizer,
    )

# How many of the most recent digest's themes are offered to the summarizer as
# carry-forward candidates. Bounded to one period back by design: continuity
# still compounds across a longer run (each saved digest carries its own
# carried-forward themes into the next), without this use case ever scanning
# unbounded history.
_LOOKBACK_LIMIT = 1


@dataclass(frozen=True, slots=True)
class BuildDigestRequest:
    since: datetime
    until: datetime
    cadence: Cadence


def _still_eligible(theme: Theme, today: date) -> bool:
    """A candidate to offer the summarizer: not already past its own deadline.

    A theme with no `relevant_until` is still offered — recurrence-based
    continuity has no date to expire by, so it's the Summarizer's call whether
    it's still actually recurring or has gone stale."""
    return theme.relevant_until is None or theme.relevant_until >= today


def _rank_key(theme: Theme, today: date) -> tuple[int, float]:
    if theme.relevant_until is not None and theme.relevant_until >= today:
        return (0, (theme.relevant_until - today).days)
    weight = theme.source_count + (theme.streak - 1) + theme.personal_weight
    return (1, -weight)


class BuildDigestUseCase:
    """Takes concrete port implementations at construction time (dependency injection);
    never imports adapter packages directly."""

    def __init__(
        self,
        email_source: EmailSource,
        summarizer: Summarizer,
        publisher: DigestPublisher,
        repository: DigestRepository,
        weighers: Sequence[RelevanceWeigher] = (),
    ) -> None:
        self._email_source = email_source
        self._summarizer = summarizer
        self._publisher = publisher
        self._repository = repository
        self._weighers = weighers

    def _weigh(self, theme: Theme) -> Theme:
        if not self._weighers:
            return theme
        total = sum(weigher.weight_for(theme.title) for weigher in self._weighers)
        return replace(theme, personal_weight=total)

    def execute(self, request: BuildDigestRequest) -> Digest:
        today = request.until.date()
        prior_themes = [
            theme
            for _, prior_digest in self._repository.list_recent(limit=_LOOKBACK_LIMIT)
            for theme in prior_digest.themes
            if _still_eligible(theme, today)
        ]

        messages = self._email_source.fetch_since(request.since)
        themes = self._summarizer.summarize(messages, prior_themes=prior_themes, today=today)
        weighed = (self._weigh(theme) for theme in themes)
        ranked = tuple(sorted(weighed, key=lambda theme: _rank_key(theme, today)))
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
        self._repository.save(digest)
        return digest
