"""Boundary interfaces. Core defines these; adapter packages implement them.

Nothing in this file may import a concrete adapter — the dependency points
inward, from adapters toward these Protocols, never the other way.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date, datetime

    from ranked_digest.entities import Digest, EmailMessage, Theme


class EmailSource(Protocol):
    """Fetches raw messages for a given window. Implemented by an adapter package."""

    def fetch_since(self, since: datetime) -> list[EmailMessage]: ...


class Summarizer(Protocol):
    """Turns a batch of messages, plus the themes still live from prior periods,
    into this period's full theme list. Implemented by an adapter package.

    `prior_themes` are the still-unexpired themes from the most recent digest(s)
    (an upcoming `relevant_until`, or just continuing to recur) — this is how the
    summarizer recognizes "this is the same theme as last period's X" and decides
    whether to carry it forward (setting `Theme.carried_forward=True`, preserving
    its `theme_key`, bumping `streak`) even when nothing new mentions it this
    period. This judgment call belongs here, not in the use case, because it's
    semantic ("is this the same topic, worded differently") rather than
    mechanical. The use case trusts whatever theme list comes back and only
    handles the deterministic part: final ranking and building the Digest.
    """

    def summarize(
        self, messages: list[EmailMessage], *, prior_themes: list[Theme], today: date
    ) -> list[Theme]: ...


class RelevanceWeigher(Protocol):
    """Scores how much a candidate (a theme's title) matters to this specific reader —
    a float, not a bool, so an adapter can express "a little" vs "a lot" without core
    caring why. The translation from some personal signal (a knowledge base, a scrobble
    history, anything) into that number is entirely the adapter's judgment; core only
    ever sums whatever configured weighers return (see BuildDigestUseCase) into a
    theme's ranking weight. Zero weighers configured (the default) means zero
    personalization — the generic program doesn't know or care whether this port has
    any implementation at all.
    """

    def weight_for(self, candidate: str) -> float: ...


class DigestPublisher(Protocol):
    """Renders a finished Digest somewhere a human will read it."""

    def publish(self, digest: Digest) -> None: ...


class DigestRepository(Protocol):
    """Persists digests and makes past ones retrievable, keyed by an opaque slug.

    The slug's format is the repository implementation's own business (a
    filename, a database id, whatever) — callers only ever get one back from
    `save` or `list_recent` and pass it back to `get`, never construct one.
    """

    def save(self, digest: Digest) -> str: ...

    def list_recent(self, limit: int = 20) -> list[tuple[str, Digest]]: ...

    def get(self, slug: str) -> Digest | None: ...
