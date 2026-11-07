"""Helpers every provider shares, so the contract is implemented once, not per vendor:
input sanitising, retry with backoff, and a small JSON-Schema subset check of the output."""

from __future__ import annotations

__arbor__ = {"ring": "llm"}

from typing import TYPE_CHECKING, TypeVar

from llmhost.errors import LlmOutputError, LlmTimeoutError, LlmUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable

    from llmhost.contracts import CompletionRequest

MAX_INPUT_CHARS = 400_000
_TRUNCATED = "\n[truncated by llmhost]"

T = TypeVar("T")


def clean_input(text: str) -> str:
    """Drop NUL characters (some servers choke on them) and bound the size."""
    text = text.replace("\x00", "")
    if len(text) > MAX_INPUT_CHARS:
        return text[:MAX_INPUT_CHARS] + _TRUNCATED
    return text


def with_retries(
    attempt: Callable[[], T],
    *,
    max_retries: int,
    backoff_s: float,
    sleep: Callable[[float], None],
) -> T:
    """Run `attempt` up to `max_retries + 1` times; only timeouts and unavailability retry."""
    last: LlmTimeoutError | LlmUnavailableError | None = None
    for n in range(max_retries + 1):
        if n:
            sleep(backoff_s * 2 ** (n - 1))
        try:
            return attempt()
        except (LlmTimeoutError, LlmUnavailableError) as exc:
            last = exc
    raise last or LlmUnavailableError("no attempt was made")


def input_schema(request: CompletionRequest) -> dict[str, object]:
    """The JSON Schema of the tool's input: the `input_schema` of an Anthropic-style tool
    definition, or the schema itself when the caller passed a bare one. `{}` if none."""
    schema = request.tool_schema
    inner = schema.get("input_schema")
    if isinstance(inner, dict):
        return {str(k): v for k, v in inner.items()}
    return schema if "type" in schema else {}


def validate_output(value: object, request: CompletionRequest) -> dict[str, object]:
    """The tool input must be a JSON object that satisfies the request's schema."""
    if not isinstance(value, dict):
        msg = "model output is not a JSON object"
        raise LlmOutputError(msg)
    schema = input_schema(request)
    if schema:
        _check(value, schema, "$")
    return {str(k): v for k, v in value.items()}


_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "boolean": (bool,),
    "integer": (int,),
    "number": (int, float),
    "null": (type(None),),
}


def _check(value: object, schema: dict[str, object], path: str) -> None:
    _check_type(value, schema, path)
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        msg = f"{path} is not one of the allowed values"
        raise LlmOutputError(msg)
    if isinstance(value, dict):
        _check_object(value, schema, path)
    items = schema.get("items")
    if isinstance(value, list) and isinstance(items, dict):
        for i, item in enumerate(value):
            _check(item, items, f"{path}[{i}]")


def _check_type(value: object, schema: dict[str, object], path: str) -> None:
    wanted = schema.get("type")
    if not isinstance(wanted, str) or wanted not in _TYPES:
        return
    is_bool_for_number = isinstance(value, bool) and wanted in {"integer", "number"}
    if is_bool_for_number or not isinstance(value, _TYPES[wanted]):
        msg = f"{path} must be of type {wanted}"
        raise LlmOutputError(msg)


def _check_object(value: dict[str, object], schema: dict[str, object], path: str) -> None:
    required = schema.get("required")
    for key in required if isinstance(required, list) else []:
        if key not in value:
            msg = f"{path}.{key} is required"
            raise LlmOutputError(msg)
    props = schema.get("properties")
    if isinstance(props, dict):
        for key, sub in props.items():
            if key in value and isinstance(sub, dict):
                _check(value[key], sub, f"{path}.{key}")
