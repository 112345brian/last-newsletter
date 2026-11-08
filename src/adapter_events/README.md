# last-newsletter-adapter-events

Implements core's `EventExtractor` with a **local** Ollama model (through `llmhost`).

Tiers, cheapest first: embedded JSON-LD/.ics (core's `EmbeddedEventReader`, not here) ->
date-signal pre-filter (no date/time-like text means no model call) -> local model with a
JSON-Schema-constrained answer -> evidence guard -> optional cloud escalation (off by default,
needs both an `Escalator` and `escalate=True`; no real cloud client ships).

Guard: every candidate's `evidence` must be a (whitespace-insensitive) substring of the email,
otherwise it is rejected and counted in `extractor.stats.rejected`. The model never resolves a
missing year; `PartialWhen` stays partial for core's rule.

Backend trouble raises `ExtractionFailed`, so ingest leaves the batch unprocessed.

The model is reached only through `llmhost.Provider`, so it is one spec string -- local or cloud:

```python
from last_newsletter_adapter_events import LocalLlmEventExtractor

extractor = LocalLlmEventExtractor.from_spec("ollama:gpt-oss:120b")  # local
extractor = LocalLlmEventExtractor.from_spec("claude:<model id>")  # cloud, no other change
```

`LocalLlmEventExtractor(provider, model)` takes any `llmhost.Provider`. The old
`LocalLlmEventExtractor(OllamaClient(OllamaConfig(model=...)))` shape still works (a thin shim
that builds an `llmhost` Ollama provider); `base_url=None` means the default local server.

Evaluation (needs Ollama, not part of `make check`): `scripts/eval_events.py`.
