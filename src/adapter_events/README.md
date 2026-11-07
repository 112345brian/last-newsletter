# last-newsletter-adapter-events

Implements core's `EventExtractor` with a **local** Ollama model (standard library only).

Tiers, cheapest first: embedded JSON-LD/.ics (core's `EmbeddedEventReader`, not here) ->
date-signal pre-filter (no date/time-like text means no model call) -> local model with a
JSON-Schema-constrained answer -> evidence guard -> optional cloud escalation (off by default,
needs both an `Escalator` and `escalate=True`; no real cloud client ships).

Guard: every candidate's `evidence` must be a (whitespace-insensitive) substring of the email,
otherwise it is rejected and counted in `extractor.stats.rejected`. The model never resolves a
missing year; `PartialWhen` stays partial for core's rule.

Backend trouble raises `ExtractionFailed`, so ingest leaves the batch unprocessed.

```python
from last_newsletter_adapter_events import LocalLlmEventExtractor, OllamaClient, OllamaConfig

client = OllamaClient(OllamaConfig(model="...", base_url="http://localhost:11434"))
extractor = LocalLlmEventExtractor(client)
```

Evaluation (needs Ollama, not part of `make check`): `scripts/eval_events.py`.
