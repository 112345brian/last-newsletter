"""Concrete Summarizer: groups messages into cross-source themes via an LLM.

The actual provider call, and recording what it cost, is `llmhost`'s job (provider
chosen by name, Claude by default, bring-your-own-key, nothing sent to a third-party
SaaS backend other than the model provider the user configures) — this module is the
newsletter-specific half: the tool schema to ask for, and resolving what comes back
into `Theme`s. Everything the use case computes mechanically (`source_count` via
`_verified`, ranking) is left to it; this adapter only resolves what's semantic: which
themes exist, which prior ones continue (by matching `theme_key`), and each one's
`streak`/`first_seen`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, cast

from last_newsletter_core.entities import Theme
from llmhost import CompletionRequest, record_usage, resolve

if TYPE_CHECKING:
    from pathlib import Path

    from last_newsletter_core.entities import EmailMessage
    from llmhost import Provider

_TOOL_NAME = "record_themes"
_BODY_EXCERPT_CHARS = 1500

_TOOL_SCHEMA: dict[str, Any] = {
    "name": _TOOL_NAME,
    "description": "Record this period's cross-source themes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "themes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "source_message_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "message_id of every fetched message that covers "
                            "this theme. Empty for a carried-forward theme nothing new "
                            "mentioned.",
                        },
                        "theme_key": {
                            "type": ["string", "null"],
                            "description": "Stable identifier reused across periods for the "
                            "same topic. Copy a prior theme's theme_key verbatim when this is "
                            "that same topic continuing; invent a short new one (e.g. "
                            "'kubernetes-1.32-release') for a genuinely new theme.",
                        },
                        "relevant_until": {
                            "type": ["string", "null"],
                            "description": "ISO date (YYYY-MM-DD) of a known future date this "
                            "theme is about (a deadline, a conference), else null.",
                        },
                        "carried_forward": {
                            "type": "boolean",
                            "description": "True iff this theme_key matches one of the prior "
                            "themes offered below.",
                        },
                    },
                    "required": ["title", "summary", "source_message_ids", "carried_forward"],
                },
            }
        },
        "required": ["themes"],
    },
}

_SYSTEM_PROMPT = (
    "You read a batch of newsletter emails and identify the themes/topics they cover, "
    "merging the same topic across different senders into one theme. You also decide "
    "which themes from the prior period are still ongoing (continuing recurrence, or an "
    "unexpired future date) versus which have run their course. Call record_themes exactly "
    "once with your full answer."
)


def _format_messages(messages: list[EmailMessage]) -> str:
    if not messages:
        return "(no new messages this period)"
    lines = [
        f"- message_id: {message.message_id}\n"
        f"  source: {message.source_label or message.sender}\n"
        f"  subject: {message.subject}\n"
        f"  received_at: {message.received_at.isoformat()}\n"
        f"  body: {message.body_text[:_BODY_EXCERPT_CHARS]}"
        for message in messages
    ]
    return "\n".join(lines)


def _format_prior_themes(prior_themes: list[Theme]) -> str:
    if not prior_themes:
        return "(none — this is the first period, or none are still eligible)"
    lines = [
        f"- theme_key: {theme.theme_key}\n"
        f"  title: {theme.title}\n"
        f"  summary: {theme.summary}\n"
        f"  streak: {theme.streak}\n"
        f"  relevant_until: {theme.relevant_until}"
        for theme in prior_themes
    ]
    return "\n".join(lines)


def _parse_relevant_until(raw: str | None) -> date | None:
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _to_theme(raw: dict[str, Any], prior_by_key: dict[str, Theme], today: date) -> Theme:
    theme_key = raw.get("theme_key") or None
    carried_forward = bool(raw.get("carried_forward", False))
    prior = prior_by_key.get(theme_key) if theme_key is not None else None

    if carried_forward and prior is not None:
        streak = prior.streak + 1
        first_seen = prior.first_seen or today
    else:
        carried_forward = False
        streak = 1
        first_seen = today

    source_message_ids = tuple(raw.get("source_message_ids") or ())
    return Theme(
        title=raw["title"],
        summary=raw["summary"],
        source_count=len(set(source_message_ids)),
        source_message_ids=source_message_ids,
        theme_key=theme_key,
        relevant_until=_parse_relevant_until(raw.get("relevant_until")),
        first_seen=first_seen,
        streak=streak,
        carried_forward=carried_forward,
    )


class AnthropicSummarizer:
    """Implements last_newsletter_core.ports.Summarizer.

    Named for the default provider, not the mechanism: the actual call goes through
    `llmhost`'s provider registry (`provider` is a name it resolves, e.g. "claude"),
    so a future `LAST_NEWSLETTER_LLM_PROVIDER=openai` is a config change here, not a
    rewrite.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-5-5",
        *,
        provider: str = "claude",
        usage_ledger_path: Path | None = None,
        _provider_override: Provider | None = None,
    ) -> None:
        """`usage_ledger_path`, if given, gets one `llmhost.record_usage` line per call.
        `_provider_override` is test-only -- production code gets its provider from
        `llmhost.resolve(provider)`."""
        self._model = model
        self._provider_name = provider
        self._provider: Provider = (
            _provider_override if _provider_override is not None else resolve(provider)
        )
        self._usage_ledger_path = usage_ledger_path

    def summarize(
        self, messages: list[EmailMessage], *, prior_themes: list[Theme], today: date
    ) -> list[Theme]:
        if not messages and not prior_themes:
            return []

        user_prompt = (
            f"Today's date: {today.isoformat()}\n\n"
            f"Prior period's still-eligible themes:\n{_format_prior_themes(prior_themes)}\n\n"
            f"This period's fetched messages:\n{_format_messages(messages)}"
        )
        result = self._provider.complete_with_tool(
            CompletionRequest(
                model=self._model,
                system=_SYSTEM_PROMPT,
                user_message=user_prompt,
                tool_schema=_TOOL_SCHEMA,
                tool_name=_TOOL_NAME,
                max_tokens=4096,
            )
        )
        if self._usage_ledger_path is not None:
            record_usage(
                self._usage_ledger_path,
                provider=self._provider_name,
                purpose="summarize",
                usage=result.usage,
                at=datetime.now(tz=UTC),
            )

        # `tool_input` is `dict[str, object]` -- llmhost's contract is provider-agnostic and
        # can't know this call's own schema shape. `themes` is this adapter's own tool schema
        # (above), so it's the one place that gets to assume what's actually in it.
        raw_themes = cast("list[dict[str, Any]]", result.tool_input.get("themes", []))
        prior_by_key = {
            theme.theme_key: theme for theme in prior_themes if theme.theme_key is not None
        }
        return [_to_theme(raw, prior_by_key, today) for raw in raw_themes]
