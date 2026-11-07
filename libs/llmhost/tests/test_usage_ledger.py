from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from llmhost.contracts import Usage
from llmhost.usage_ledger import record_usage, total_tokens

if TYPE_CHECKING:
    from pathlib import Path


def test_total_tokens_is_zero_for_a_ledger_that_does_not_exist_yet(tmp_path: Path) -> None:
    assert total_tokens(tmp_path / "usage.jsonl") == 0


def test_record_usage_then_total_tokens_sums_input_and_output(tmp_path: Path) -> None:
    ledger_path = tmp_path / "nested" / "usage.jsonl"
    at = datetime(2026, 1, 5, tzinfo=UTC)

    record_usage(
        ledger_path,
        provider="claude",
        purpose="summarize",
        usage=Usage(model="claude-sonnet-5-5", input_tokens=100, output_tokens=20),
        at=at,
    )
    record_usage(
        ledger_path,
        provider="claude",
        purpose="summarize",
        usage=Usage(model="claude-sonnet-5-5", input_tokens=50, output_tokens=10),
        at=at,
    )

    assert total_tokens(ledger_path) == 180


def test_record_usage_with_tokens_unavailable_contributes_zero(tmp_path: Path) -> None:
    ledger_path = tmp_path / "usage.jsonl"
    at = datetime(2026, 1, 5, tzinfo=UTC)

    record_usage(
        ledger_path,
        provider="claude",
        purpose="summarize",
        usage=Usage(model="claude-sonnet-5-5", tokens_available=False),
        at=at,
    )

    assert total_tokens(ledger_path) == 0
