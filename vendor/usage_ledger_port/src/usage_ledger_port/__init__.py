"""The usage ledger as a budget gate sees it: rows read, and a "skipped for budget" row written.

Install::

    usage_ledger_port @ git+https://github.com/112345brian/bripe-job-search.git@<sha>#subdirectory=libs/usage_ledger_port

``UsageLedger`` is the Protocol an adapter implements; ``UsageLedgerSlot`` holds the one bound to a process and
raises ``UsageLedgerNotBound`` when none is, so a process that skipped the bind cannot read "no spend". Standard
library only.
"""
from usage_ledger_port.ledger_port import UsageLedger, UsageLedgerNotBound, UsageLedgerSlot

__all__ = ["UsageLedger", "UsageLedgerNotBound", "UsageLedgerSlot"]
