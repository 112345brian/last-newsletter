"""Counters the caller can read after `extract`: what was skipped, rejected, escalated."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class ExtractionStats:
    messages: int = 0
    prefiltered_out: int = 0
    model_calls: int = 0
    schema_failures: int = 0
    escalated: int = 0
    escalation_errors: int = 0
    candidates: int = 0
    rejected: Counter[str] = field(default_factory=Counter)
    failed_message_ids: list[str] = field(default_factory=list)
