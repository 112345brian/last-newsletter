"""Typed errors: the only exceptions a `Provider` may raise. No message carries prompt text."""

from __future__ import annotations

__arbor__ = {"ring": "llm"}


class LlmError(Exception):
    """Base class: the model could not give a usable answer for this request."""


class LlmConfigError(LlmError, ValueError):
    """A provider spec is malformed or names something that does not exist."""


class UnknownProviderError(LlmConfigError):
    """The provider name is not in the registry."""


class LlmUnavailableError(LlmError):
    """Connection refused / unreachable / rate limited / HTTP 5xx, after all retries."""


class LlmTimeoutError(LlmError):
    """No answer within the timeout on every attempt."""


class LlmProtocolError(LlmError):
    """The server answered, but not with something we understand (bad status, not an envelope)."""


class LlmOutputError(LlmError):
    """The model's output is empty, not JSON, not an object, or violates the tool schema."""
