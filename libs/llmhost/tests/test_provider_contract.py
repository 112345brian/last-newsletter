"""The contract every registered provider must pass. Add a provider to `llmhost.REGISTRY` and
this suite fails until `harnesses.HARNESSES` has a harness for it and the harness passes.

Contract: `complete_with_tool` returns a result whose `tool_input` is a JSON object satisfying
the request's schema, with honest `Usage`; transient trouble is retried a bounded number of
times; and the ONLY exceptions that ever escape are `llmhost.LlmError` subclasses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from harnesses import GOOD, HARNESSES, MODEL, Harness, Step

from llmhost import (
    REGISTRY,
    CompletionRequest,
    LlmError,
    LlmOutputError,
    LlmProtocolError,
    LlmTimeoutError,
    LlmUnavailableError,
)
from llmhost.checks import MAX_INPUT_CHARS

if TYPE_CHECKING:
    from collections.abc import Iterator

SCHEMA: dict[str, object] = {
    "name": "report",
    "description": "report the result",
    "input_schema": {
        "type": "object",
        "properties": {"n": {"type": "integer"}, "label": {"type": "string", "enum": ["a", "b"]}},
        "required": ["n"],
    },
}
ATTEMPTS = 3  # first try + max_retries (2) in every harness


def request(user: str = "hello", system: str = "be brief") -> CompletionRequest:
    return CompletionRequest(
        model=MODEL, system=system, user_message=user, tool_schema=SCHEMA, tool_name="report"
    )


@pytest.fixture(params=sorted(HARNESSES))
def harness(request: pytest.FixtureRequest) -> Iterator[Harness]:
    h = HARNESSES[request.param]()
    yield h
    h.close()


def test_every_registered_provider_has_a_contract_harness() -> None:
    assert set(REGISTRY) == set(HARNESSES), (
        "a provider in llmhost.REGISTRY needs a harness in tests/harnesses.py "
        "(and every harness needs a registry entry)"
    )


def test_normal_result(harness: Harness) -> None:
    result = harness.build(Step()).complete_with_tool(request())
    assert result.tool_input == GOOD
    assert result.usage.model == MODEL
    assert harness.attempts == 1


def test_usage_is_taken_from_the_vendor(harness: Harness) -> None:
    usage = harness.build(Step(tokens=(11, 7))).complete_with_tool(request()).usage
    assert (usage.input_tokens, usage.output_tokens) == (11, 7)
    assert usage.tokens_available is True


def test_missing_usage_is_unknown_not_zero(harness: Harness) -> None:
    usage = harness.build(Step(tokens=None)).complete_with_tool(request()).usage
    assert usage.tokens_available is False


@pytest.mark.parametrize("kind", ["empty", "malformed", "wrong_shape", "schema_violation"])
def test_bad_model_output_is_an_output_error(harness: Harness, kind: str) -> None:
    with pytest.raises(LlmOutputError):
        harness.build(Step(kind=kind)).complete_with_tool(request())


def test_timeout_then_success(harness: Harness) -> None:
    result = harness.build(Step(kind="timeout"), Step()).complete_with_tool(request())
    assert result.tool_input == GOOD
    assert harness.attempts == 2


def test_persistent_timeout_is_bounded_and_typed(harness: Harness) -> None:
    with pytest.raises(LlmTimeoutError):
        harness.build(Step(kind="timeout")).complete_with_tool(request())
    assert harness.attempts == ATTEMPTS


@pytest.mark.parametrize("kind", ["unavailable", "server_error"])
def test_persistent_outage_is_bounded_and_typed(harness: Harness, kind: str) -> None:
    with pytest.raises(LlmUnavailableError):
        harness.build(Step(kind=kind)).complete_with_tool(request())
    assert harness.attempts == ATTEMPTS


def test_client_errors_are_protocol_errors_and_not_retried(harness: Harness) -> None:
    with pytest.raises(LlmProtocolError):
        harness.build(Step(kind="bad_status")).complete_with_tool(request())
    assert harness.attempts == 1


@pytest.mark.parametrize(
    "kind",
    [
        "timeout",
        "unavailable",
        "server_error",
        "bad_status",
        "empty",
        "malformed",
        "wrong_shape",
        "schema_violation",
    ],
)
def test_only_typed_llmhost_errors_escape(harness: Harness, kind: str) -> None:
    provider = harness.build(Step(kind=kind))
    # Any other exception type propagates out of `raises` and fails the test.
    with pytest.raises(LlmError):
        provider.complete_with_tool(request())


def test_nul_is_stripped_and_huge_input_is_bounded(harness: Harness) -> None:
    huge = "ab\x00cd" + "x" * 2_000_000
    harness.build(Step()).complete_with_tool(request(user=huge, system="sys\x00tem"))
    assert harness.sent, "the vendor was never called"
    for text in harness.sent:
        assert "\x00" not in text
        assert len(text) <= MAX_INPUT_CHARS + 100
    assert "system" in harness.sent[0]
