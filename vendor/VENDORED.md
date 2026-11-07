# Vendored code

Managed by [dfetch](https://dfetch.readthedocs.io) — see `dfetch.yaml` at the repo root. Each directory under
`vendor/` is a copy of a standalone repo `github.com/112345brian/<name-with-dashes>`, pinned to its own tag
(`v0.1.0`; `process_lock` and `durable_outbox` are `v0.1.1`). Do not hand-edit `vendor/`; run `uvx dfetch update` to re-fetch.

Consumer-specific changes live in `patches/<name>.patch` and are re-applied on every fetch. Today that is only
`durable_outbox`'s `pyproject.toml`, which points `process-lock` at the workspace member instead of its git tag.
Ring membership (`core`/`adapters`/...) is a property of how *this* repo uses each library, so it is not annotated in
the vendored source: `arborescent.toml`'s `[classify]` table maps these modules to rings by name.
The tests for `process_lock` and `durable_outbox` ship with the upstream repos (v0.1.1) under `vendor/*/tests`.

Rules: ruff and ty skip `vendor/`; import-linter and the workspace-layout test do not. `core` must
not import any of these (it owns its own defaults); they sit beside `core`, `text_match` and `mailtext` and are
used only through adapters.

## Not vendored: `libs/llmhost`

`libs/llmhost` is a trimmed early fork (~210 lines) of the `llmhost` repo, not a dfetch copy. Upstream v0.3.0 is
~5,400 lines and its API is not a drop-in: it has no `CompletionRequest`, no tool-use call
(`complete_with_tool` / `tool_schema` / `tool_input`) and no `resolve()`/`Provider` pair; `CompletionResult` is
generic with outcome/usage/route; text completion goes through `complete_text*` instead; and it pulls in
`pydantic`, `requests` and `genai-prices`. The only caller, `adapter_summarizer` (`anthropic_summarizer.py`), depends
on the tool-use shape, so migrating means rewriting it and its tests, not re-pointing an import. Left as a fork until
that is a deliberate piece of work (issue #1).
