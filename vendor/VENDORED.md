# Vendored code

Managed by [dfetch](https://dfetch.readthedocs.io) — see `dfetch.yaml` at the repo root. Each directory under
`vendor/` is a copy of a standalone repo `github.com/112345brian/<name-with-dashes>`, pinned to its own tag. Do not
hand-edit `vendor/`; run `uvx dfetch update` to re-fetch.

Only `process_lock` (`v0.1.1`) is vendored now. It is the one shared library this repo imports (the raw message store,
the atomic file writer and the ledger take its cross-process lock).

**Rule: vendor only what is imported.** Eight more libraries (`urgency`, `identity_dedupe`, `source_dates`,
`text_normalize`, `notification_port`, `usage_ledger_port`, `durable_outbox`, `tracker_state`) were vendored when the
project was started from the job-search template, but nothing here ever imported them, and several of the things they
do (event identity, text normalisation) are done differently on purpose for events. They were removed; vendor one again
only in the commit that first imports it.

Ring membership (`core`/`adapters`/...) is a property of how *this* repo uses each library, so it is not annotated in
the vendored source: `arborescent.toml`'s `[classify]` table maps these modules to rings by name.

Rules: ruff and ty skip `vendor/`; import-linter and the workspace-layout test do not.

## Not vendored: `libs/llmhost`

`libs/llmhost` is a trimmed early fork (~210 lines) of the `llmhost` repo, not a dfetch copy. Upstream v0.3.0 is
~5,400 lines and its API is not a drop-in: it has no `CompletionRequest`, no tool-use call
(`complete_with_tool` / `tool_schema` / `tool_input`) and no `resolve()`/`Provider` pair; `CompletionResult` is
generic with outcome/usage/route; text completion goes through `complete_text*` instead; and it pulls in
`pydantic`, `requests` and `genai-prices`. The only caller, `adapter_summarizer` (`anthropic_summarizer.py`), depends
on the tool-use shape, so migrating means rewriting it and its tests, not re-pointing an import. Left as a fork until
that is a deliberate piece of work (issue #1).
