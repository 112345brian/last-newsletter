"""HTTP transport for ntfy pushes: the only place in this lib that talks urllib.

Policy (which priority spools on failure, how a request is built) goes through the small :class:`NtfyTransport`
interface instead of calling ``urllib.request`` directly, so a test exercises spool/retry behavior with a fake
transport rather than mocking urllib internals or standing up an HTTP server.

The default :class:`UrllibNtfyTransport`: ``send`` propagates any exception to the caller (which wraps it in its own
best-effort try/except), and ``is_healthy`` swallows all exceptions and reports ``False``.
"""
from __future__ import annotations

__arbor__ = {"ring": "core"}

import urllib.request
from typing import Protocol


class NtfyTransport(Protocol):
    """Everything notify.py's domain logic needs from an ntfy-compatible
    HTTP endpoint. Small and swappable so tests can inject a fake."""

    def send(self, request: urllib.request.Request, *, timeout: int) -> None:
        """POST ``request``. Raise on any non-2xx response or connection
        failure — callers are responsible for catching and translating
        that into their own best-effort outcome (spool, log, etc.)."""
        ...

    def is_healthy(self, url: str, *, timeout: int) -> bool:
        """GET ``url`` and return True only for an HTTP 200 response.
        Never raises — any failure (timeout, connection refused, non-200)
        reports unhealthy."""
        ...


class UrllibNtfyTransport:
    """Default transport: real HTTP via the standard-library ``urllib``."""

    def send(self, request: urllib.request.Request, *, timeout: int) -> None:
        with urllib.request.urlopen(request, timeout=timeout):
            pass

    def is_healthy(self, url: str, *, timeout: int) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False
