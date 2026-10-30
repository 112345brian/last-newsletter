"""Concrete Summarizer: groups messages into cross-source themes via the Claude API.

Bring-your-own API key (ANTHROPIC_API_KEY env var) — nothing is sent to a third-party
SaaS backend other than the model provider the user configures. Prompting and
response-parsing are not written yet; this locks in the port signature.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    from last_newsletter_core.entities import EmailMessage, Theme


class AnthropicSummarizer:
    """Implements last_newsletter_core.ports.Summarizer."""

    def __init__(self, model: str = "claude-sonnet-5-5") -> None:
        self._model = model

    def summarize(
        self, messages: list[EmailMessage], *, prior_themes: list[Theme], today: date
    ) -> list[Theme]:
        msg = "LLM summarization not yet implemented"
        raise NotImplementedError(msg)
