"""Typed errors of the local-model backend. None of them carries email text."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}


class ModelBackendError(Exception):
    """Base class: the model could not give an answer for this request."""


class ModelUnavailableError(ModelBackendError):
    """Connection refused / host unreachable / HTTP 5xx after all retries (Ollama down)."""


class ModelTimeoutError(ModelBackendError):
    """No answer within the timeout on every attempt."""


class ModelProtocolError(ModelBackendError):
    """The server answered, but not with the envelope we expect (bad HTTP status, not JSON)."""


class ModelOutputError(ModelBackendError):
    """The model's text is empty, not JSON, or violates the requested schema."""


class EscalationError(Exception):
    """The optional cloud escalator failed; the extractor keeps the local result."""
