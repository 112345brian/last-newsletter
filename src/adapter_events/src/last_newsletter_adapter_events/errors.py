"""Typed errors of the model backend. The `Model*` names are llmhost's errors under their old
names, so callers that catch them keep working; none of them carries email text."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

from llmhost import (
    LlmError,
    LlmOutputError,
    LlmProtocolError,
    LlmTimeoutError,
    LlmUnavailableError,
)

ModelBackendError = LlmError
ModelUnavailableError = LlmUnavailableError
ModelTimeoutError = LlmTimeoutError
ModelProtocolError = LlmProtocolError
ModelOutputError = LlmOutputError


class EscalationError(Exception):
    """The optional cloud escalator failed; the extractor keeps the local result."""
