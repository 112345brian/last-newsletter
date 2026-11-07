# llmhost

The **one** interface through which this repo talks to a language model. Local or cloud, the
caller writes the same code and picks the model with a spec string.

```python
from pathlib import Path
from llmhost import CompletionRequest, record_usage, resolve_model

resolved = resolve_model("ollama:gpt-oss:120b")  # or "claude:claude-sonnet-5-5"
result = resolved.provider.complete_with_tool(
    CompletionRequest(
        model=resolved.model,
        system="...",
        user_message="...",
        tool_schema={"name": "report", "description": "...", "input_schema": {...}},
        tool_name="report",
        max_tokens=4096,
    )
)
record_usage(Path("usage.jsonl"), provider=resolved.name, purpose="summarize", usage=result.usage)
```

## Spec strings

`provider` or `provider:model`, split at the **first** colon (the model may contain more):

| Spec | Meaning |
|------|---------|
| `claude` | Claude, caller supplies the model id |
| `claude:<model id>` | Claude with that model |
| `ollama:gpt-oss:120b` | local Ollama, model `gpt-oss:120b` |
| `ollama` | local Ollama, caller supplies the model |

Registered providers: **`claude`** (needs `ANTHROPIC_API_KEY`), **`ollama`** (server from
`LLMHOST_OLLAMA_URL`, default the local one). An unknown name raises `UnknownProviderError`
listing the known ones. `resolve(spec)` returns only the provider; `resolve_model(spec)` also
returns the provider name and model part.

## The contract (every provider, enforced)

`Provider.complete_with_tool(request) -> CompletionResult`:

- `tool_input` is a JSON **object** that satisfies the tool's `input_schema` (types, enums,
  required, nested items). Empty, non-JSON, non-object or schema-violating output raises
  `LlmOutputError` -- it is never returned.
- `usage` is honest: counts come from the vendor; if the vendor reports none,
  `tokens_available=False` (unknown, not zero).
- Inputs are sanitised: NUL characters removed, text capped at `MAX_INPUT_CHARS`.
- Transient trouble (timeout, connection failure, HTTP 429/5xx) is retried a bounded number of
  times with backoff; the final failure is `LlmTimeoutError` / `LlmUnavailableError`. Other
  HTTP errors are `LlmProtocolError` and are not retried.
- **Only `LlmError` subclasses ever escape** -- never an SDK or `urllib` exception.
- Temperature is 0 where the vendor allows it.

`tests/test_provider_contract.py` is one parametrized suite run against every provider (Claude
through a fake SDK client, Ollama against a real local fake HTTP server).
`test_every_registered_provider_has_a_contract_harness` fails when `REGISTRY` and
`tests/harnesses.py` disagree, so a provider cannot be added without passing the suite.

## Adding a provider

1. `src/llmhost/provider_<name>.py`: a class with `complete_with_tool`, built from the shared
   helpers in `checks.py` (`clean_input`, `with_retries`, `validate_output`) and raising only
   the errors in `errors.py`. Keep any vendor SDK import inside this file.
2. One entry in `REGISTRY` (`providers.py`): `"<name>": <zero-argument factory>`.
3. A harness in `tests/harnesses.py` (script the vendor's behaviours, record what it was sent)
   and add it to `HARNESSES`. Run `pytest libs/llmhost`.
4. If it needs a new third-party package, list it in `libs/llmhost/pyproject.toml` and under
   `[ring.llm] external` in `arborescent.toml`. No other ring may list a model SDK.

## Enforcement (fails `make check`)

`tests/test_single_llm_interface.py` and `arborescent.toml` make "everything goes through
`Provider`" a build failure, not a convention:

- no module outside `libs/llmhost` imports `anthropic`, `openai`, `ollama` or another model SDK,
  or contains a known model endpoint (`localhost:11434`, `api.anthropic.com`, ...);
- every caller of `complete_with_tool` / `resolve` / `resolve_model` uses the result and does
  not swallow `LlmError` (`bare call`, `_ = ...`, `except Exception: pass`, `suppress(...)`);
- `llmhost` lives in its own ring, `llm`, the only one whose `external` lists `anthropic`.

No newsletter, no IMAP, no app-specific concept anywhere in it.
