"""The notification port: what application code may ask of "something that can push a phone alert".

This module is the inner ring's *interface*. It owns the ``Notifier`` protocol and the ``NotifyResult`` outcome type
and imports nothing that does I/O. An adapter (ntfy, a spool, a tracker restart) implements ``Notifier``; only an
entrypoint constructs it and hands it down. Use cases take a ``Notifier`` argument, so a test passes an in-memory fake
and needs no server, spool file or environment variable.

Callers must consume the ``NotifyResult`` a ``push`` returns.
"""
from __future__ import annotations

__arbor__ = {"ring": "core"}

import enum
from typing import Protocol


class NotifyResult(enum.Enum):
    """Outcome of one notification-delivery attempt.

    ``bool(result)`` is True only for ``DELIVERED``, so ``if push(...)`` still means "the user got it";
    callers that must react differently to "nothing configured" vs. "failed" vs. "spooled, will retry"
    match on the enum value instead.
    """

    DELIVERED = "delivered"        # accepted by the ntfy server
    UNCONFIGURED = "unconfigured"  # NTFY_TOPIC not set -- nothing to send, not a failure
    SPOOLED = "spooled"            # send failed but queued for redelivery (high/urgent only)
    FAILED = "failed"              # send failed and was not (or could not be) spooled
    SKIPPED = "skipped"            # no-op guard fired before attempting delivery

    def __bool__(self) -> bool:
        return self is NotifyResult.DELIVERED


class Notifier(Protocol):
    """Send operator-facing alerts. Every method is best effort and never raises."""

    def push(
        self,
        title: str,
        body: str,
        *,
        priority: str = "default",
        tags: str = "",
        click: str | None = None,
        actions: list[dict[str, object]] | None = None,
    ) -> NotifyResult:
        """Send one alert. ``priority`` is ntfy's scale: min, low, default, high, urgent."""
        ...

    def ensure_server_up(self, *, try_restart: bool = True) -> bool:
        """Whether the notification channel is reachable, restarting it once if ``try_restart``."""
        ...
