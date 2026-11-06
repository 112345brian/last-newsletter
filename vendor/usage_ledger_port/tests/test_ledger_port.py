from __future__ import annotations

import pytest

from usage_ledger_port import UsageLedger, UsageLedgerNotBound, UsageLedgerSlot


class _Ledger:
    def __init__(self) -> None:
        self.skips: list[str] = []

    def load_rows(self) -> list[dict[str, object]]:
        return [{"tag": "t"}]

    def record_budget_skip(self, *, call_site: str, provider: str, model: str, reason: str) -> None:
        self.skips.append(call_site)


def test_unbound_slot_raises_rather_than_reporting_no_spend() -> None:
    slot = UsageLedgerSlot()
    assert slot.is_bound() is False
    with pytest.raises(UsageLedgerNotBound):
        slot.get()


def test_bind_get_and_unbind() -> None:
    slot = UsageLedgerSlot()
    ledger: UsageLedger = _Ledger()
    slot.bind(ledger)
    assert slot.is_bound() and slot.get() is ledger
    slot.bind(None)
    with pytest.raises(UsageLedgerNotBound):
        slot.get()


def test_slots_are_independent() -> None:
    a, b = UsageLedgerSlot(), UsageLedgerSlot()
    a.bind(_Ledger())
    assert b.is_bound() is False
