"""`EventExtractor` implementation: pre-filter -> local model -> validate -> (optional) escalate."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import dataclasses
from typing import TYPE_CHECKING

from last_newsletter_adapter_events.errors import (
    EscalationError,
    ModelBackendError,
    ModelOutputError,
)
from last_newsletter_adapter_events.prefilter import has_date_signal
from last_newsletter_adapter_events.prompt import SYSTEM_PROMPT, PromptInput, build_user_prompt
from last_newsletter_adapter_events.schema import EVENT_SCHEMA, RawEvent, parse_model_output
from last_newsletter_adapter_events.stats import ExtractionStats
from last_newsletter_adapter_events.text import clean_text, squash
from last_newsletter_adapter_events.when import parse_when
from last_newsletter_core.event_ports import ExtractionFailed
from last_newsletter_core.events import EntityRef, EntityRole, EventCandidate, EventKind

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from last_newsletter_adapter_events.escalation import Escalator
    from last_newsletter_adapter_events.ollama import OllamaClient
    from last_newsletter_core.entities import EmailMessage

_MAX_EVENTS_PER_EMAIL = 60
_FIELDS = {f.name for f in dataclasses.fields(EventCandidate)}


class LocalLlmEventExtractor:
    """Implements `last_newsletter_core.event_ports.EventExtractor`.

    Backend trouble (Ollama down, timeout) raises `ExtractionFailed` for the batch, so ingest
    leaves those messages unprocessed and retries later. A model answer that stays invalid after
    one repeat is counted in `stats.schema_failures`, and the message is listed in
    `stats.failed_message_ids`. Escalation runs only when an `Escalator` was given AND
    `escalate=True`, and only for low-confidence or invalid local results.
    """

    def __init__(
        self,
        client: OllamaClient,
        *,
        escalator: Escalator | None = None,
        escalate: bool = False,
    ) -> None:
        self._client = client
        self._escalator = escalator if escalate else None
        self.stats = ExtractionStats()

    def extract(
        self, messages: Sequence[EmailMessage], *, now: datetime, home_tz: str
    ) -> list[EventCandidate]:
        out: list[EventCandidate] = []
        for message in messages:
            out.extend(self._one(message, now=now, home_tz=home_tz))
        return out

    def _one(self, message: EmailMessage, *, now: datetime, home_tz: str) -> list[EventCandidate]:
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
        self, message: EmailMessage, subject: str, body: str, *, now: datetime, home_tz: str
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
                text = self._client.chat(system=SYSTEM_PROMPT, user=user, schema=EVENT_SCHEMA)
                return parse_model_output(text)[:_MAX_EVENTS_PER_EMAIL], False
            except ModelOutputError:
                self.stats.schema_failures += 1
            except ModelBackendError as exc:
                msg = f"local model unavailable: {type(exc).__name__}: {exc}"
                raise ExtractionFailed(msg) from exc
        return [], True

    def _escalate(
        self, escalator: Escalator, message: EmailMessage, subject: str, body: str
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
                accepted.append(_candidate(event, message_id, home_tz))
        return accepted, low_conf


def _candidate(event: RawEvent, message_id: str, home_tz: str) -> EventCandidate:
    entities = tuple(
        EntityRef(name=name.strip(), role=EntityRole.ORGANIZER)
        for name in event.organizers
        if name.strip()
    )
    if event.venue.strip():
        entities = (EntityRef(name=event.venue.strip(), role=EntityRole.VENUE), *entities)
    details = [
        f"{label}: {value}"
        for label, value in (
            ("city", event.city),
            ("tags", ", ".join(event.tags)),
            ("price", event.price),
            ("age", event.age),
        )
        if value.strip()
    ]
    candidate = EventCandidate(
        message_id=message_id,
        title=event.title.strip(),
        kind=EventKind(event.kind),
        summary="; ".join(details),
        when=parse_when(event.start_text, event.end_text, tz=home_tz),
        evidence=event.evidence.strip(),
        entities=entities,
        url=event.url.strip() or None,
    )
    # Core's candidate has no cancellation flag yet; set one if it ever grows one.
    if "is_cancelled" in _FIELDS:
        return dataclasses.replace(candidate, is_cancelled=event.cancelled)
    return candidate
