__arbor__ = {"ring": "adapters"}

from last_newsletter_adapter_events.errors import (
    EscalationError,
    ModelBackendError,
    ModelOutputError,
    ModelProtocolError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from last_newsletter_adapter_events.escalation import Escalator, FakeEscalator
from last_newsletter_adapter_events.extractor import LocalLlmEventExtractor
from last_newsletter_adapter_events.ollama import OllamaClient, OllamaConfig
from last_newsletter_adapter_events.stats import ExtractionStats

__all__ = [
    "EscalationError",
    "Escalator",
    "ExtractionStats",
    "FakeEscalator",
    "LocalLlmEventExtractor",
    "ModelBackendError",
    "ModelOutputError",
    "ModelProtocolError",
    "ModelTimeoutError",
    "ModelUnavailableError",
    "OllamaClient",
    "OllamaConfig",
]
