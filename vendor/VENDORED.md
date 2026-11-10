# Vendored code

Managed by [dfetch](https://dfetch.readthedocs.io) — see `dfetch.yaml` at the repo root. Each directory under
`vendor/` is a copy of a standalone repo `github.com/112345brian/<name-with-dashes>`, pinned to its own tag. Do not
hand-edit `vendor/`; run `uvx dfetch update` to re-fetch.

Two things are vendored now:

- `process_lock` (`v0.1.1`): the cross-process lock the raw message store and the atomic file writer take.
- `concert_tracker` (`v0.2.1`, private repo `112345brian/concert-tracker`): the event ledger. This repo imports four of
  its packages: `core` (what counts as the same event, ingest use cases, ports), `adapter_ledger` (SQLite), `ngram_index`
  (the local similar-event index) and `app` (open the ledger under its lock, keep the index in step). They live at
  `vendor/concert_tracker/src/<name>`. dfetch cannot copy a nested package whose own directory holds a `src/`, so the
  whole repo comes in and `ignore` in `dfetch.yaml` prunes the rest: the source adapters (Ticketmaster, calendars, venue
  pages), its CLI, the optional embedding backend, its tests (they run upstream) and its own copy of `process_lock`.
  Mail is just one more source for that ledger: `last_newsletter_adapter_storage.documents` maps `EmailMessage` to the
  ledger's `SourceDocument`. To change event behaviour, change concert-tracker, tag it, bump `tag:` in `dfetch.yaml`
  and run `uvx dfetch update concert_tracker`; do not edit the copy.

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
