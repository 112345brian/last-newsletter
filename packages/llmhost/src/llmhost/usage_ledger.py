"""Per-call token usage ledger: one JSON line appended per completion call.

A plain append-only file rather than a database -- the whole point is that
recording a call never risks losing the call itself, so the write has to be
one `open(...).write()`, not a schema migration away from working.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from llmhost.contracts import Usage


def record_usage(
    ledger_path: Path, *, provider: str, purpose: str, usage: Usage, at: datetime
) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": at.isoformat(), "provider": provider, "purpose": purpose, **asdict(usage)}
    with ledger_path.open("a", encoding="utf-8") as ledger_file:
        ledger_file.write(json.dumps(entry) + "\n")


def total_tokens(ledger_path: Path) -> int:
    """Input + output tokens across every recorded call, or 0 if nothing's been
    recorded yet. Entries with `tokens_available=False` contribute 0, not an
    unknown amount mistaken for a real count."""
    if not ledger_path.exists():
        return 0
    total = 0
    with ledger_path.open(encoding="utf-8") as ledger_file:
        for raw_line in ledger_file:
            stripped = raw_line.strip()
            if not stripped:
                continue
            entry = json.loads(stripped)
            if not entry.get("tokens_available", True):
                continue
            total += entry.get("input_tokens", 0) + entry.get("output_tokens", 0)
    return total
