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

__arbor__ = {"ring": "core"}

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ranked_digest.entities import Digest

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime

    from ranked_digest.entities import Cadence, EmailMessage, Theme
    from ranked_digest.ports import (
        DigestPublisher,
        DigestRepository,
        EmailSource,
        RelevanceWeigher,
        Summarizer,
    )

# Only the single most recent *preceding* digest feeds carry-forward candidates to the
# summarizer. Bounded to one period back by design: continuity still compounds across a longer
# run (each saved digest carries its own carried-forward themes into the next), without this
# use case ever scanning unbounded history. `_SCAN_LIMIT` is how many saved digests are looked
# through to find that one, since re-runs and overlapping windows can sit in front of it.
_SCAN_LIMIT = 20


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


def _preceding_digest(digests: Sequence[Digest], request: BuildDigestRequest) -> Digest | None:
    """The newest saved digest that directly precedes this window: same cadence, and ending
    at or before this window starts. A digest for this same period (a re-run) or one that
    overlaps it isn't "last period", and offering it back would bump streaks on every re-run.
    `digests` is newest-first, as `DigestRepository.list_recent` returns it."""
    return next(
        (
            digest
            for digest in digests
            if digest.cadence is request.cadence and digest.period_end <= request.since
        ),
        None,
    )


def _source_key(message: EmailMessage) -> str:
    return message.source_label or message.sender


def _verified(theme: Theme, messages: Sequence[EmailMessage]) -> Theme:
    """Replace the summarizer's own `source_count` with what the messages it cites support.

    "How many sources covered this" is the headline ranking signal, and counting distinct
    sources is mechanical, so it's derived here rather than taken from an LLM's say-so:

    - Cited ids that match a fetched message count by distinct source; ids that match nothing
      (a hallucinated id) are ignored.
    - A carried-forward theme with no new mention keeps its prior count: nothing this period
      can confirm or deny it.
    - A claim citing nothing verifiable is capped at the distinct sources actually seen.
    """
    by_id = {message.message_id: message for message in messages}
    cited = [by_id[i] for i in theme.source_message_ids if i in by_id]
    if cited:
        return replace(theme, source_count=len({_source_key(m) for m in cited}))
    if theme.carried_forward or not messages:
        return theme
    seen = len({_source_key(m) for m in messages})
    return replace(theme, source_count=min(theme.source_count, seen))


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
        preceding = _preceding_digest(
            [digest for _, digest in self._repository.list_recent(limit=_SCAN_LIMIT)], request
        )
        prior_themes = [
            theme
            for theme in (preceding.themes if preceding is not None else ())
            if _still_eligible(theme, today)
        ]

        # `EmailSource` only takes a start; the end of the window is enforced here, so a
        # message that arrives after `until` belongs to the next digest, not to both.
        messages = [
            m
            for m in self._email_source.fetch_since(request.since)
            if m.received_at < request.until
        ]
        themes = self._summarizer.summarize(messages, prior_themes=prior_themes, today=today)
        weighed = (self._weigh(_verified(theme, messages)) for theme in themes)
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
