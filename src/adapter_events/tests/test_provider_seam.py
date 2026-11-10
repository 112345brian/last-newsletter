"""The extractor talks to `llmhost.Provider` only: any provider + model works, and local vs
cloud is one spec string."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from concert_tracker_core.event_ports import ExtractionFailedError

from last_newsletter_adapter_events import LocalLlmEventExtractor, OllamaClient, OllamaConfig
from llmhost import (
    REGISTRY,
    CompletionRequest,
    CompletionResult,
    LlmOutputError,
    LlmUnavailableError,
    Usage,
)

from .conftest import NOW, event, msg

if TYPE_CHECKING:
    from llmhost import Provider


class FakeProvider:
    """Stands in for any vendor: returns the scripted tool input, records the requests."""

    def __init__(self, result: dict[str, object] | Exception) -> None:
        self.result = result
        self.requests: list[CompletionRequest] = []

    def complete_with_tool(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return CompletionResult(tool_input=self.result, usage=Usage(model=request.model))


BODY = "Moon Party Sat Dec 12, 9pm at the Barn"


def extract(provider: Provider, model: str = "m") -> int:
    ex = LocalLlmEventExtractor(provider, model)
    return len(ex.extract([msg(BODY)], now=NOW, home_tz="UTC"))


def test_any_provider_object_works() -> None:
    fake = FakeProvider({"events": [event()]})
    assert extract(fake, "some-model") == 1
    request = fake.requests[0]
    assert request.model == "some-model"
    assert request.tool_name == "report_events"
    assert "input_schema" in request.tool_schema


def test_local_and_cloud_are_one_spec_string(monkeypatch: pytest.MonkeyPatch) -> None:
    local, cloud = FakeProvider({"events": [event()]}), FakeProvider({"events": [event()]})
    registry = cast("dict[str, object]", REGISTRY)
    monkeypatch.setitem(registry, "fakelocal", lambda: local)
    monkeypatch.setitem(registry, "fakecloud", lambda: cloud)
    for spec, fake, model in [
        ("fakelocal:gpt-oss:120b", local, "gpt-oss:120b"),
        ("fakecloud:c-1", cloud, "c-1"),
    ]:
        ex = LocalLlmEventExtractor.from_spec(spec)
        assert len(ex.extract([msg(BODY)], now=NOW, home_tz="UTC")) == 1
        assert fake.requests[0].model == model


def test_from_spec_without_a_model_is_rejected() -> None:
    with pytest.raises(ValueError, match="model name"):
        LocalLlmEventExtractor.from_spec("ollama")


def test_provider_outage_still_fails_the_batch() -> None:
    ex = LocalLlmEventExtractor(FakeProvider(LlmUnavailableError("down")), "m")
    with pytest.raises(ExtractionFailedError):
        ex.extract([msg(BODY)], now=NOW, home_tz="UTC")


def test_schema_violation_from_a_provider_is_counted_not_fatal() -> None:
    ex = LocalLlmEventExtractor(FakeProvider(LlmOutputError("bad")), "m")
    assert ex.extract([msg(BODY)], now=NOW, home_tz="UTC") == []
    assert ex.stats.schema_failures == 2
    assert ex.stats.failed_message_ids == ["m1"]


def test_compat_client_carries_provider_and_model() -> None:
    client = OllamaClient(OllamaConfig(model="gpt-oss:120b"))
    assert client.model == "gpt-oss:120b"
    assert callable(client.provider.complete_with_tool)
    LocalLlmEventExtractor(client)  # the old constructor shape still works


def test_compat_config_defaults_do_not_name_an_endpoint() -> None:
    assert OllamaConfig(model="m").base_url is None
