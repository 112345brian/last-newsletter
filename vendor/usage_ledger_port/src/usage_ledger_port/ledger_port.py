"""The usage-ledger interface and the slot that holds its binding.

A budget gate decides from already-loaded ledger rows and records why an optional call was skipped; where the rows
live is not its business. An unbound slot raises: a process that skipped the bind must not read "no spend" and wave
every optional call through.

The slot is an object, not module state: the application creates one and decides who binds it.
"""
from __future__ import annotations

from typing import Protocol


class UsageLedger(Protocol):
    def load_rows(self) -> list[dict[str, object]]:
        """Every ledger row (dicts with at least ``tag``, ``executor``, ``estimated_cost_usd``, a timestamp)."""
        ...

    def record_budget_skip(self, *, call_site: str, provider: str, model: str, reason: str) -> None:
        """Append one explicit skipped-for-budget row. Best effort: a failed ledger write must not raise."""
        ...


class UsageLedgerNotBound(RuntimeError):
    """The ledger was used before anything bound one."""


class UsageLedgerSlot:
    """Holds at most one bound :class:`UsageLedger`."""

    def __init__(self) -> None:
        self._ledger: UsageLedger | None = None

    def bind(self, ledger: UsageLedger | None) -> None:
        """Bind *ledger*; ``None`` unbinds."""
        self._ledger = ledger

    def is_bound(self) -> bool:
        return self._ledger is not None

    def get(self) -> UsageLedger:
        """The bound ledger. Raises :class:`UsageLedgerNotBound` when none is."""
        if self._ledger is None:
            raise UsageLedgerNotBound("no usage ledger bound: call UsageLedgerSlot.bind(...) at the entrypoint")
        return self._ledger
