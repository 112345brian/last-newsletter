# One interface for every LLM call

**Rule:** any code that uses a language model reaches it through `llmhost.Provider`
(`libs/llmhost`). Which model runs is a *spec string* (`ollama:gpt-oss:120b`,
`claude:<model id>`), so moving a per-email step between a local and a cloud model is a config
change, not a code change.

## Shape

- `Provider.complete_with_tool(CompletionRequest) -> CompletionResult` -- the tool's
  `input_schema` constrains the answer (Claude: forced tool call; Ollama: JSON-schema `format`).
- `resolve_model("provider:model")` consults one registry (`llmhost.REGISTRY`).
- Failures are `LlmError` subclasses (`Output`, `Timeout`, `Unavailable`, `Protocol`, `Config`),
  never vendor exceptions. Adapters translate them (`adapter_events`: output errors are a counted
  retry, everything else raises `ExtractionFailedError` so ingest retries later).

## Rings

`llmhost` is the only member of the `llm` ring (`arborescent.toml`): it may read the environment,
sleep between retries and import `anthropic`; no other ring may list a model SDK. Adapters may
import `llm`; core and the standalone libs may not.

## Enforcement

| Rule | Where it fails |
|------|----------------|
| Every provider honours the contract | `libs/llmhost/tests/test_provider_contract.py` (parametrized) |
| A registered provider has a harness | `test_every_registered_provider_has_a_contract_harness` |
| No SDK import / model endpoint outside llmhost | `test_single_llm_interface.py` (AST scan) |
| Callers use results and errors | same file (AST scan, with self-tests of the scanner) |
| Only ring `llm` lists `anthropic` | `arborescent.toml` + `test_only_the_llm_ring_may_list_anthropic` |

How to add a provider: `libs/llmhost/README.md`.

## Open item

`libs/llmhost` is still a trimmed fork, not upstream `llmhost` v0.3.0 (tracked in GitHub issue 1);
this contract is what an upstream migration has to satisfy.
