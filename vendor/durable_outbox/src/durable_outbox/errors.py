"""Errors raised by the outbox."""
from __future__ import annotations


class OutboxWriteError(RuntimeError):
    """The hosted outbox itself could not be written (disk full, permissions, a lock that
    never freed). The one failure of an upload that is allowed to fail a stage:
    the data has nowhere left to go. Defined here (a pure type) so inner rings can catch it
    without importing ``state.hosted_outbox``."""
