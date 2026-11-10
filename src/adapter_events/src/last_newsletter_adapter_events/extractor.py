"""`EventExtractor` implementation: pre-filter -> local model -> validate -> (optional) escalate."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import dataclasses
from typing import TYPE_CHECKING

from concert_tracker_core.event_ports import ExtractionFailedError
from concert_tracker_core.events import EntityRef, EntityRole, EventCandidate, EventKind

from last_newsletter_adapter_events.compat import OllamaClient
from last_newsletter_adapter_events.errors import EscalationError
from last_newsletter_adapter_events.prefilter import has_date_signal
from last_newsletter_adapter_events.prompt import SYSTEM_PROMPT, PromptInput, build_user_prompt
from last_newsletter_adapter_events.schema import EVENT_TOOL, RawEvent, parse_events
from last_newsletter_adapter_events.stats import ExtractionStats
from last_newsletter_adapter_events.text import clean_text, squash
from last_newsletter_adapter_events.when import parse_when, split_listing
from llmhost import CompletionRequest, LlmError, LlmOutputError, resolve_model

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from concert_tracker_core.documents import SourceDocument

    from last_newsletter_adapter_events.escalation import Escalator
    from llmhost import Provider

_MAX_EVENTS_PER_EMAIL = 60
_FIELDS = {f.name for f in dataclasses.fields(EventCandidate)}


class LocalLlmEventExtractor:
    """Implements `concert_tracker_core.event_ports.EventExtractor`.

    Backend trouble (Ollama down, timeout) raises `ExtractionFailedError` for the batch, so ingest
    leaves those messages unprocessed and retries later. A model answer that stays invalid after
    one repeat is counted in `stats.schema_failures`, and the message is listed in
    `stats.failed_message_ids`. Escalation runs only when an `Escalator` was given AND
    `escalate=True`, and only for low-confidence or invalid local results.
    """

    def __init__(
        self,
        provider: Provider | OllamaClient,
        model: str = "",
        *,
        escalator: Escalator | None = None,
        escalate: bool = False,
    ) -> None:
        """`provider` is any `llmhost.Provider` and `model` the name it should be asked for.
        (An `OllamaClient` is accepted for compatibility and supplies both.)"""
        if isinstance(provider, OllamaClient):
            provider, model = provider.provider, model or provider.model
        if not model:
            msg = "a model name is required"
            raise ValueError(msg)
        self._provider: Provider = provider
        self._model = model
        self._escalator = escalator if escalate else None
        self.stats = ExtractionStats()

    @classmethod
    def from_spec(
        cls,
        spec: str,
        *,
        escalator: Escalator | None = None,
        escalate: bool = False,
    ) -> LocalLlmEventExtractor:
        """Build from a ``provider:model`` spec such as ``ollama:gpt-oss:120b`` or
        ``claude:<model id>``: swapping local for cloud is changing this one string."""
        resolved = resolve_model(spec)
        return cls(resolved.provider, resolved.model, escalator=escalator, escalate=escalate)

    def extract(
        self, messages: Sequence[SourceDocument], *, now: datetime, home_tz: str
    ) -> list[EventCandidate]:
        out: list[EventCandidate] = []
        for message in messages:
            out.extend(self._one(message, now=now, home_tz=home_tz))
        return out

    def _one(self, message: SourceDocument, *, now: datetime, home_tz: str) -> list[EventCandidate]:
        stats = self.stats
        stats.messages += 1
        body = clean_text(message.body_text)
        subject = clean_text(message.subject, limit=300)
        if not has_date_signal(subject, body):
            stats.prefiltered_out += 1
            return []
        source = squash(f"{subject}\n{body}")

        raw, invalid = self._ask_local(message, subject, body, now=now, home_tz=home_tz)
        accepted, low_conf = self._validate(raw, message.message_id, source, home_tz)
        if self._escalator is not None and (invalid or low_conf):
            second = self._escalate(self._escalator, message, subject, body)
            accepted = self._validate(second, message.message_id, source, home_tz)[0] or accepted
        if invalid and not accepted:
            stats.failed_message_ids.append(message.message_id)
        stats.candidates += len(accepted)
        return accepted

    def _ask_local(
        self, message: SourceDocument, subject: str, body: str, *, now: datetime, home_tz: str
    ) -> tuple[list[RawEvent], bool]:
        user = build_user_prompt(
            PromptInput(
                subject=subject,
                sender=clean_text(message.sender, limit=300),
                received=message.received_at.isoformat(),
                body=body,
                today=now.date().isoformat(),
                home_tz=home_tz,
            )
        )
        for _attempt in range(2):  # one repeat for malformed/empty output
            self.stats.model_calls += 1
            try:
                result = self._provider.complete_with_tool(
                    CompletionRequest(
                        model=self._model,
                        system=SYSTEM_PROMPT,
                        user_message=user,
                        tool_schema=EVENT_TOOL,
                        tool_name=str(EVENT_TOOL["name"]),
                    )
                )
                return parse_events(result.tool_input)[:_MAX_EVENTS_PER_EMAIL], False
            except LlmOutputError:
                self.stats.schema_failures += 1
            except LlmError as exc:
                msg = f"local model unavailable: {type(exc).__name__}: {exc}"
                raise ExtractionFailedError(msg) from exc
        return [], True

    def _escalate(
        self, escalator: Escalator, message: SourceDocument, subject: str, body: str
    ) -> list[RawEvent]:
        self.stats.escalated += 1
        try:
            return escalator.escalate(message_id=message.message_id, subject=subject, text=body)
        except EscalationError:
            self.stats.escalation_errors += 1
            return []

    def _validate(
        self, raw: list[RawEvent], message_id: str, source: str, home_tz: str
    ) -> tuple[list[EventCandidate], bool]:
        accepted: list[EventCandidate] = []
        low_conf = False
        for event in raw:
            quote = squash(event.evidence)
            if not quote:
                self.stats.rejected["empty_evidence"] += 1
            elif quote not in source:
                self.stats.rejected["evidence_not_in_source"] += 1
            elif not event.title.strip():
                self.stats.rejected["empty_title"] += 1
            else:
                low_conf = low_conf or event.confidence == "low"
                accepted.extend(_candidates(event, message_id, home_tz))
        return accepted, low_conf


def _candidates(event: RawEvent, message_id: str, home_tz: str) -> list[EventCandidate]:
    """One candidate per listed date: a listing naming several days is several events, each with
    its own UUID (docs/design/event-ledger.md section 3), sharing the quoted evidence line."""
    days = split_listing(event.start_text)
    end_text = event.end_text if len(days) == 1 else ""
    return [_candidate(event, message_id, home_tz, day, end_text) for day in days]


def _candidate(
    event: RawEvent, message_id: str, home_tz: str, start_text: str, end_text: str
) -> EventCandidate:
    entities = tuple(
        EntityRef(name=name.strip(), role=EntityRole.ORGANIZER)
        for name in event.organizers
        if name.strip()
    )
    if event.venue.strip():
        entities = (EntityRef(name=event.venue.strip(), role=EntityRole.VENUE), *entities)
    summary = ""
    if event.cancelled and "is_cancelled" not in _FIELDS:
        # Never let a cancellation look like a live event: say so until core has a flag.
        summary = "CANCELLED"
    candidate = EventCandidate(
        message_id=message_id,
        title=event.title.strip(),
        kind=EventKind(event.kind),
        summary=summary,
        when=parse_when(start_text, end_text, tz=home_tz),
        evidence=event.evidence.strip(),
        entities=entities,
        url=event.url.strip() or None,
        city=event.city.strip(),
        tags=frozenset(t.strip() for t in event.tags if t.strip()),
        price=event.price.strip(),
        age=event.age.strip(),
    )
    # Core's candidate has no cancellation flag yet; set one if it ever grows one.
    if "is_cancelled" in _FIELDS:
        return dataclasses.replace(candidate, is_cancelled=event.cancelled)
    return candidate
