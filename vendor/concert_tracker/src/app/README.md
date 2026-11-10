# concert-tracker-app

The logic a front end needs to work with the event ledger, with no front end in it. The
`concert-tracker` command is a thin layer over this; another project that feeds events in
vendors this instead of copying it.

| Name | What it is |
| --- | --- |
| `ledger_session(data_dir, dry_run=, prepare=)` | Opens the ledger and the similarity index under the one-writer lock. A dry run works on a throwaway copy and saves nothing real. Yields a `LedgerSession` (`.ledger`, `.index`, `.events_dir`, `.notes`, `.sync_index()`). |
| `CoreSimilarIndex`, `sync_index`, `LINK_ONLY_POLICY` | Adapt the local similarity index to core's `SimilarEventIndex` port, keep it in step with the ledger, and the identity policy that lets a similarity score *link* two events but never *merge* them. |
| `ledger_session(..., extra_indexes=[factory])`, `CombinedSimilarIndex`, `SimilarBackend` | Optional extra similarity indexes (such as the embedding one). Each factory is called with the session's directory; the backend is synced, closed at the end, and anything it could not do is added to `session.notes`. `session.similar_index` is what ingest should be given: all indexes behind core's one port. |
| `render_text`, `render_json` | Show stored events with the mentions that cite each. |
| `ConfigError`, `IdGenerator`, `Uuid4Ids` | What a command raises for a bad setting, and where new event ids come from (randomness is an effect, so it lives outside core). |

```python
from concert_tracker_app import ledger_session, CoreSimilarIndex, LINK_ONLY_POLICY
from concert_tracker_core.use_cases import IngestEvents, IngestPorts

with ledger_session(data_dir, dry_run=False) as session:
    session.sync_index()
    ingest = IngestEvents(
        IngestPorts(repository=session.ledger, ..., similar_index=CoreSimilarIndex(session.index)),
        home_tz="America/Los_Angeles",
        policy=LINK_ONLY_POLICY,
    )
```

**What it imports:** core, `adapter_ledger`, `ngram_index`. **What it does not:** any source
adapter (Ticketmaster, Frequent Flyer, ...) or the CLI. That is why a consumer can vendor it without
carrying the sources.
