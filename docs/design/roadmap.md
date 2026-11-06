# Roadmap: core first, features in stages

Status: draft 1, 2026-11-06. Replaces the build order in `event-ledger.md` section 11 (which stays as the short version). Behavior is in `product-spec.md`.

## The approach

**Wire the whole core at once; ship features stage by stage.** Core is the inner ring: entities, rules, ports, fakes and use cases for everything in the spec (ledger, editions, sections, alerts, corrections). It has no dependencies, so building all of it costs no vendor lock-in and no IO. A stage then means one thing only: **which real adapters and screens are plugged into ports that already exist.** Nothing in core changes between stages except to fix a bug.

Two rules make this safe:

1. **A port with no adapter yet is bound to a "not available" implementation.** Every port ships with one that returns a typed `Unavailable(reason)` result (the job repo's `PortNotBound` pattern, vendored in `usage_ledger_port`). Use cases handle it as an outcome, and it shows in "Needs a look". So the full flow runs at every stage, with fewer capabilities turned on, and a feature that is not built yet cannot crash or silently do nothing. A test asserts every port has a not-available binding and every use case handles it.
2. **Features are gated by configuration, not by branches of code.** The composition root in `cli` binds adapters according to the stage; `EditionConfig`, `TriggerConfig` and `SectionSpec` already express what the owner turns on.

**The risk of wiring core all at once** is designing for facts we do not have yet. Two parts of the spec rest on open decisions: whether title + date + venue is enough for identity, and the reminder channel. Importance is decided (the owner's knowledge store, per extracted entity, through the existing `RelevanceWeigher` port); only its thresholds wait for real data. Core builds the open parts as *ports with a simple default* (identity = the ladder with every match recorded and re-runnable, reminders = the `Notifier` port), and a later stage replaces the default once measured data exists. Core does not hard-code a guess.

## Stages

Each stage has an exit test: something that can be run, not a feeling.

### Stage 0: scaffold (done)
Workspace checks, vendored libs (`vendor/`), design, product spec, research.
Exit: `pytest`, `ruff`, `ty` and `lint-imports` clean (met).

### Stage 1: complete core
Everything in the spec, no real IO.
- Entities: `Event` (with `sale_start`, `tags`, state, mentions), `ItemTime`, `Mention`, `EventCandidate`, `PartialWhen`.
- Rules: year resolution, default one-week task deadline, resurface once, past-date rejection, cancellation, identity ladder.
- Delivery and layout: `issue_due`, `plan_alerts`, `place` (sections), config validation.
- Ports and fakes: every port in design section 6, each with an in-memory fake and a not-available binding.
- Use cases: `IngestEvents`, `ListReminders`, `ApplyAction` (done, dismiss, snooze, correct, merge, split), `PublishIssue`, `SendAlerts`.
- Guard tests: core imports stdlib only; no IO or ambient state in core; no caller discards a use-case result; the `pyproject` lists agree.

Exit: one scenario test runs ingest -> ledger -> a weekly issue with a Concerts section -> a presale alert -> a done action, all on fakes, with zero third-party packages installed in core's environment.

### Stage 2: storage
`adapter_ledger` (SQLite): items, mentions, state, raw message store, extraction queue, delivery log, issue log. One contract suite per port, run against the fake and the SQLite adapter.
Exit: both pass the same suites; re-ingesting the same email changes nothing (first-seen preserved); a crash between "decide" and "send" neither loses nor duplicates an alert.

### Stage 3: ingest without a model
IMAP source (exists), embedded-event reader (calendar attachments, structured data), tag rules, a `cli ingest` command, a plain-text issue written to a file.
Exit: run against the real mailbox; report what share of newsletters carry machine-readable events. That number decides how much Stage 4 must do.

### Stage 4: model extraction
Extractor adapter (returns **entities**: headliner, support acts, venue, organizer), extraction queue with retry, cost and privacy admission, a small labeled sample of real mail. The knowledge weigher is wired to the extracted names here.
Exit: precision and recall on the sample, including how often a clean headliner name is extracted and how often it matches a knowledge entity; and a measured duplicate rate. This is where the identity decision (is title + date + venue enough) is made from data, and importance is revisited.

### Stage 5: the issue on screen
Needs `DESIGN.md` first (no visual identity exists). One weekly edition, the issue screen, Up next, Item detail, Done and Dismiss and Snooze.
Exit: you can read last week's issue on a phone and clear an item, and it stays cleared after the next ingest.

### Stage 5b: Listen
Sample resolver adapters (start with one provider that works without special access), the sample store, the click-to-load player and its content security policy, a "Worth a Listen" section.
Exit: on a labeled list of about 30 artist names from your own mail, report found, ambiguous and no-match rates and the wrong-artist rate among accepted samples; the embed rule is set from that number, and nothing loads before a click (checked by a test of the rendered page).

### Stage 6: stop-press alerts
Notifier adapter (channel to be decided: ntfy or in-app), durable outbox, quiet hours, daily cap.
Exit: a presale one day out produces exactly one alert, before the sale, outside the weekly issue; a restart does not repeat it.

### Stage 7: configuration and repair
Settings screen: multiple editions, sections and tag rules; Correct, Merge, Split; Needs a look.
Exit: you add a monthly edition and a Concerts section from the screen, and the next issues reflect them.

### Later (not scheduled)
Finding nearby events that are in no email (needs outside event sources and an artist-similarity model), learning importance from behavior (done, dismiss, snooze) and writing it back to knowledge (research not done), urgency bands from the vendored `urgency` survival curve, recurring-event expansion, calendar write-back, non-English mail, attachments beyond calendar files.

## What each stage lets you demo

| After stage | You can |
|---|---|
| 1 | Run the whole flow in tests; read the spec as executable |
| 2 | Keep a real ledger on disk |
| 3 | See events pulled from your actual mail, no model cost |
| 4 | See the model fill the gaps, with measured accuracy |
| 5 | Read your first issue and clear items |
| 6 | Get a presale alert in time |
| 7 | Shape your own editions and sections |

## Order and parallelism

Stages 1 and 2 are sequential. After Stage 2, Stage 3 and the `DESIGN.md` work for Stage 5 can run in parallel (different files). Stages 4 and 6 do not depend on each other, but 6 needs Stage 5 for any in-app channel. Stage 1 is the only large piece; it is split into slices that are each green before the next (entities and rules, then ports and fakes, then use cases, then the scenario test).

## Decisions each stage needs from the owner

| Before stage | Decision |
|---|---|
| 3 | none |
| 4 | which model and budget; sender deny-list for transactional mail; the `important_at` threshold, set after seeing real weights |
| 5 | visual identity (run the design pass) |
| 5b | which providers (Spotify needs a Premium developer account; SoundCloud may need Artist Pro); your area as a list of cities |
| 6 | reminder channel: ntfy or in-app only |
| 7 | none beyond the open spec items |
