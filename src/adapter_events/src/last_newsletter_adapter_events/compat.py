"""Backward-compatible constructors: `OllamaConfig`/`OllamaClient` keep their old shape but are
now just a way to build an `llmhost` provider + model. There is no HTTP code here."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from llmhost import OllamaProvider, OllamaSettings

if TYPE_CHECKING:
    from collections.abc import Callable

    from llmhost import Provider
    from llmhost.transport import Transport


@dataclass(frozen=True, slots=True)
class OllamaConfig:
    """Everything the old client needed; built by the caller (the CLI reads env vars).
    `base_url=None` means llmhost's default (the local Ollama server)."""

    model: str
    base_url: str | None = None
    timeout_s: float = 300.0
    max_retries: int = 2  # retries after the first attempt
    backoff_s: float = 1.0
    num_ctx: int = 16384
    think: bool | str | None = None


class OllamaClient:
    """A `Provider` plus the model name to ask it for -- what `LocalLlmEventExtractor` needs."""

    def __init__(
        self,
        config: OllamaConfig,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        defaults = OllamaSettings()
        settings = OllamaSettings(
            base_url=config.base_url or defaults.base_url,
            timeout_s=config.timeout_s,
            max_retries=config.max_retries,
            backoff_s=config.backoff_s,
            num_ctx=config.num_ctx,
            think=config.think,
        )
        self.model = config.model
        self.provider: Provider = OllamaProvider(settings, transport=transport, sleep=sleep)
