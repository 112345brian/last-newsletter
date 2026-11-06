# Event and task ledger: design

Status: draft 2, 2026-11-06 (adds the six gaps in section 13, the IO-discipline test, and the verified state of job-repo libs). Inputs: `PRODUCT.md`, `docs/research/*.md`.
Tags: **[V]** verified against the repo or by computation, **[A]** assumed, **[D]** decision still open.

## 1. Goal

Add a remembered lane next to the stateless digest. Dated events, deadlines and one-time tasks extracted from newsletters become ledger items with an identity, a date, urgency and the owner's state. News stays stateless, as today.

## 2. The rule that shapes everything: dependency inversion

**Core defines every capability it needs as a port and owns every domain rule. Adapters implement ports. Nothing in core knows a library, a database, a model vendor or a notification service exists.**

Consequences, each enforced by a test rather than by prose:

1. **Core imports the standard library only.** A test parses every module in `packages/core/src` and fails on any import whose top-level name is not in `sys.stdlib_module_names` or `last_newsletter_core` **[V: attribute exists in Python 3.10+; the repo targets 3.11]**. This is stricter than the import-linter contract, which cannot whitelist. Stdlib-only is still not enough: `sqlite3`, `socket`, `urllib`, `subprocess`, `open()`, `os.environ`, `time` and `random` are all stdlib. A second AST test therefore forbids IO and ambient state in core: imports of `os`, `sys`, `io`, `pathlib`, `sqlite3`, `socket`, `urllib`, `http`, `subprocess`, `shutil`, `tempfile`, `logging`, `threading`, `asyncio`, `time`, `random`, `secrets`; calls to `open`, `print`, `input`, `datetime.now`, `datetime.today`, `date.today`, `os.getenv`; and dynamic imports. Pure stdlib stays allowed (`datetime`, `dataclasses`, `enum`, `unicodedata`, `difflib`, `re`, `zoneinfo`, `typing`, `collections`). Time enters through a `Clock` port or a `now` argument.
2. **Domain rules live in core, not in an adapter.** What counts as "the same event", how a missing year is resolved, what a default task deadline is, when a task resurfaces and what urgency means are all pure functions in core. A library may help an adapter *produce input* but never decides a rule.
3. **Every port has a hand-written fake in core's tests** (the repo's existing pattern, `core/tests/test_build_digest.py`), and the complete ingest-to-remind flow runs against fakes with no network, no disk and no clock.
4. **One contract-test suite per port**, run against the fake and against each real adapter. An adapter is acceptable when the same suite passes. Swapping SQLite for another store, or Instructor for a raw SDK call, is then a new adapter plus a passing suite, with no core change.
5. **Adapters never import each other** (existing layers contract **[V]**). If two adapters need the same code it moves to a small standalone package below the adapters, like `text_match` and `mailtext`.

## 3. Domain model (core)

All types are frozen dataclasses with no I/O. Datetimes are timezone-aware; constructors reject naive ones.

- **`Event`**: `id` (surrogate, opaque, assigned by the ledger), `kind` (`EVENT`, `DEADLINE`, `TASK`), `title`, `summary`, `when: ItemTime`, `sale_start: ItemTime | None`, `due_is_default: bool`, `entities: tuple[EntityRef, ...]`, `tags: frozenset[Tag]` (each tag records its origin: `OWNER`, `RULE`, `EXTRACTOR`), `state: ItemState`, `mentions: tuple[Mention, ...]`, `first_seen`, `last_seen`, `resurfaced: int`.
- **`EntityRef`**: `name` (as written), `role` (`HEADLINER`, `SUPPORT`, `VENUE`, `ORGANIZER`), `origin` (`OWNER`, `EXTRACTOR`). The named people and places an item is about; what importance is computed from.
- **`ItemTime`**: `AllDay(date)` or `Timed(start, tz_name, end | None)`; `TASK` items carry an `AllDay` default due date.
- **`Mention`** (provenance, never overwritten): `message_id`, `seen_at`, `source`, `raw_date_text`, `evidence` (the quoted line the item came from), `match_rule` (which identity rung linked it).
- **`ItemState`**: `OPEN`, `DONE`, `DISMISSED`, `SNOOZED(until)`, `EXPIRED`. State is separate from extracted fields so a re-extraction never overwrites what the owner did.
- **`EventCandidate`**: untrusted extractor output. Partial values allowed; the use case validates it into an `Event` or rejects it with a counted reason.
- **`PartialWhen`**: `year | None`, `month`, `day`, `weekday | None`, `time | None`, `tz | None`, `raw_text`.

`Theme` is unchanged **[V: scaffold review, section 1.1]**. It stays the digest's ranking record; the ledger does not extend it.

## 4. Domain rules (pure functions in core)

| Rule | Behavior | Why |
|---|---|---|
| Resolve missing year | Given `PartialWhen` and a reference date, choose the year in which the month, day and weekday agree; if no weekday, take the nearest future occurrence within a grace window; if still ambiguous, mark uncertain. | Survey: lists like "SATURDAY DEC 12" omit the year. **[V]** Dec 12 is a Saturday in 2026 (computed from Fri Nov 6, 2026 plus 36 days), so the weekday pins the year. |
| Default task deadline | First seen plus 7 days; `due_is_default = True`. | Owner decision 2026-11-06. |
| Resurface | A lapsed task of high importance returns once (`resurfaced` becomes 1), then expires. Never resurfaces if `DONE` or `DISMISSED`. | Owner decision. |
| Past dates | Reject if start is before now minus a grace period, unless the text marks it as a recap; count and report rejections. | LLMs invent dates. |
| Cancellation | A mention marked as cancelling moves a matching open item to `DISMISSED` with reason `cancelled_by_source`, and keeps the mention. | The survey saw a mail that cancels an event. |
| Urgency | `UrgencyPolicy.band(item, now)` returns an ordered band. Core ships a simple default (days until). | See port below; the job repo's survival curve becomes a later implementation. |

## 5. Identity (the central rule) **[D]**

Match ladder, stop at the first hit, always against open or recently closed items only. Source: `event-prior-art.md` section 6 and the job repo's `libs/identity_dedupe` ladder (now a standalone lib with a `Dedupable` protocol and an injected URL normalizer), which uses the same shape. It can serve as an adapter; core keeps its own stdlib default and one contract test runs the same cases against both.

1. iCalendar `UID` (with `RECURRENCE-ID` for one instance); a higher `SEQUENCE` updates, a lower one is ignored.
2. Canonical URL, when the item has one.
3. Normalized title + local date + venue, within a ±1 day window.
4. Otherwise a new item.

**Failure policy: when a candidate could match several items, keep it separate and link it as a possible duplicate. Showing a duplicate is safe; hiding a live item is not.** This mirrors the job repo's rule.

The normalization used by rungs 2 and 3 is **core code** (stdlib `unicodedata`). `core` cannot import `text_match` **[V: layers contract]**, and it should not, since "same event" is a domain rule. Fuzzy title similarity is a port (below) with a stdlib default.

**Open:** whether rung 3 alone is good enough. It needs a labeled sample of real repeated events. Until then rung 3 is the baseline and the match rule is recorded on every mention so decisions can be audited and re-run.

## 6. Ports (all owned by core)

| Port | Method | Default / fake in core | Candidate adapter(s) |
|---|---|---|---|
| `EmailSource` (exists) | fetch messages in a window | fake exists | IMAP (exists) |
| `EmbeddedEventReader` | `read(message) -> list[EventCandidate]` from JSON-LD, Microdata, `.ics` | empty fake | `extruct`, `icalendar` |
| `EventExtractor` | `extract(messages, *, now, home_tz) -> list[EventCandidate]`; no tools, no network beyond the model call | scripted fake | Instructor over the Anthropic SDK, or the SDK directly |
| `TextSimilarity` | `score(a, b) -> float` | stdlib `difflib` implementation | `rapidfuzz` |
| `EventRepository` | `upsert`, `find_open`, `get`, `record_mention`, `apply_action` | in-memory fake | SQLite (new `adapter_ledger`) |
| `RelevanceWeigher` (exists) | importance for resurfacing | fake exists | knowledge weigher (exists) |
| `UrgencyPolicy` | `band(item, now)` | core default | job-repo `libs/urgency` (`item_urgency`, `survival_curve`; no deps, ready) |
| `RawMessageStore` | `put(message) -> RawRef`, `get(ref)` | in-memory fake | SQLite blob table in `adapter_ledger` |
| `ExtractionQueue` | `enqueue`, `claim`, `complete`, `fail(retry_after)` | in-memory fake | SQLite table in `adapter_ledger` |
| `ModelAdmission` | `admit(request) -> Admitted \| Refused(reason)`; budget and privacy filter | permissive fake | job-repo usage-ledger shape (not yet a lib) |
| `RunLog` | `record(SourceOutcome)`; per-source health | in-memory fake | SQLite |
| `WriterLock` / `Outbox` | single writer; durable "to send" records | in-process fakes | job-repo `libs/process_lock`, `libs/durable_outbox` (adapter side only) |
| `Notifier` | `send(reminder) -> NotifyResult`, never raises, result must be consumed | recording fake | ntfy, or Apprise |
| `Clock` | `now()` | fixed fake | system clock, only in `cli` |

`now` is passed in rather than read. `datetime.now` appears once in the repo, in the CLI **[V: scaffold review]**, and stays there.

## 7. Use cases (core)

- **`IngestEvents`**: messages -> embedded reader first, extractor second -> validate each candidate -> identity ladder -> upsert or record mention -> `IngestResult` with counts (created, mentioned, rejected by reason, possible duplicates).
- **`ListReminders`**: open items, resurfacing rule applied, ordered by urgency band then importance.
- **`ApplyAction`**: `done`, `dismiss`, `snooze(until)`, `correct(fields)`, `merge(a, b)`, `split(item)`. Corrections are stored as overrides so a later extraction does not undo them.
- **`SendReminders`**: `ListReminders` -> `Notifier`; a cooldown per item so one item is not sent repeatedly (pattern from the job repo's deadline alert).

`BuildDigestUseCase` is not modified. Digest and ledger share the email fetch but nothing else.

## 8. Package layout

```
packages/core/                 + event entities, rules, ports, the four use cases (stdlib only)
packages/adapter_ledger/       SQLite EventRepository
packages/adapter_events/       EmbeddedEventReader + EventExtractor (extruct, icalendar, Instructor)
packages/adapter_notify/       Notifier (ntfy or Apprise)
packages/adapter_web/          + triage endpoints/pages (done, dismiss, snooze, correct)
packages/cli/                  + `ingest`, `remind` commands, wiring, the only clock
```

New packages must be added to all three lists in the root `pyproject.toml` (`members`, `root_packages`, the layers row). The existing stale `packages/libraries` member is fixed first. A test asserts the three lists agree **[V: drift confirmed, scaffold review section 2.2]**.

`adapter_events` owns its model client. The summarizer's real adapter is still a stub **[V]**, so a shared client package is deferred until two adapters need one **[D]**.

## 9. Security

Mail is untrusted input. The extractor has no tools and no outbound reach beyond the model call; it returns a schema and nothing else. The web UI never renders raw email HTML or follows links. An extracted `evidence` quote is checked to be a substring of the source message, so a hallucinated item with no source is rejected.

## 10. Test plan (written before code)

1. Architecture: core stdlib-only; core has no IO or ambient state (section 2); the three `pyproject` lists agree; the clock appears only in `cli`; no caller discards a use-case result.
2. Rules: year resolution (weekday pins the year, the Dec to Jan boundary, ambiguity marked), default due date, resurface once, never after done, past-date rejection, cancellation.
3. Identity ladder: UID update ordering, URL match, title+date+venue match, same title on different dates stays separate, ambiguous stays split and linked.
4. Use cases against fakes: ingest counts, idempotent re-ingest of the same email, state survives re-extraction, cooldown, `Notifier` failure does not lose the reminder.
5. Edge inputs: empty body, NUL characters, partial candidate, duplicate events inside one email, all-day vs timed, an item with no evidence.
6. Port contract suites, run against fakes and, as adapters land, the real ones.

Per the global rule on shared code: before changing `RelevanceWeigher` or `EmailSource`, list every caller first; this design adds ports and leaves those two unchanged.

## 11. Build order (vertical slice)

The staged plan, exit tests and decisions per stage are in `roadmap.md`; this list is the short version.

1. Fix the workspace drift and pick the single type-check command **[V: plain `ty check` has 2 test errors, `packages/*/src` is clean]**.
2. Core: entities, rules, ports, fakes, tests 1 to 3.
3. Core: use cases and tests 4 to 5 on in-memory fakes. At this point the whole design is exercised with zero dependencies.
4. `adapter_ledger` (SQLite) against the contract suite.
5. `adapter_events` with `extruct` and `icalendar` first (no model cost), then the LLM extractor.
6. `remind` command and `Notifier`.
7. Triage page.

## 12. Open decisions and unknowns

- **Decided (owner, 2026-11-06):** importance comes from the owner's knowledge store through the existing `RelevanceWeigher` port (section 14b). **[D]** still open: the thresholds, and whether the app ever writes back to knowledge.
- **[D]** Whether title + date + venue is enough for identity; needs a labeled sample from real mail.
- **[D]** Reminder channel: ntfy or the web page.
- **[D]** Shared model-client package versus per-adapter clients.
- **[A]** The share of mail that carries JSON-LD or `.ics` is unmeasured; it decides how much the LLM extractor must do.
- **[A]** Library licenses, current versions and Python 3.11 compatibility for `extruct`, `icalendar`, Instructor, `rapidfuzz` were not verified; none is imported until a session checks them.
- **Not designed here:** the page's visual design (`PRODUCT.md` exists; `DESIGN.md` does not) and recurring-event expansion (store the rule, show the next occurrence only).

## 13. Gaps closed in draft 2

Each is a decision, a typed outcome and a test in core. None adds a feature.

1. **Raw message store.** Ingest stores the source message (or a reference to it) before extraction, so a rule change can be re-run and every item traces to its email. Port `RawMessageStore`. Tracking-link query strings are stripped before storage, since they can carry per-recipient IDs.
2. **Deferred, retryable extraction.** Extraction is a queue, not an inline call. A model failure, refusal or timeout sets `retry_after` and increments attempts; after a cap the message is parked as `EXTRACTION_FAILED` and counted, never dropped and never retried forever. Port `ExtractionQueue`.
3. **Model cost and privacy admission.** Before any text leaves for a model, `ModelAdmission` checks a spend budget and a privacy filter (URLs and tracking IDs stripped, a sender deny-list for transactional and financial mail). A `Refused` outcome is recorded with its reason, and the message stays queued. The survey saw bank and order mail carrying list headers, so the deny-list is required, not optional.
4. **Source outcomes and run health.** Every run records one `SourceOutcome` per source (`OK(n)`, `EMPTY`, `FETCH_FAILED(reason)`, `PARSE_FAILED`). Silence is distinguishable from failure: a source that returns nothing for several runs raises a health flag instead of looking like "no events".
5. **Concurrency and durability.** One writer at a time (`WriterLock`), and reminders go through a durable `Outbox` so a crash between "decide to remind" and "send" neither loses nor duplicates one. Both are ports with in-process fakes in core; the real implementations may use the job repo's `process_lock` and `durable_outbox`.
6. **Idempotent upserts.** Re-ingesting the same message changes nothing (keyed by message id plus candidate hash). `first_seen` is set once and never moved; `last_seen` and `mentions` only grow; owner state and corrections are never overwritten by extraction. Each is its own test.

## 14b. Importance: from knowledge, per entity

Importance is how much the owner cares about what an item is about, for example which music artists are high priority. It is **read from the owner's knowledge store**, not learned inside this app.

- **Verified [V]:** `RelevanceWeigher.weight_for(candidate: str) -> float` exists in core (`ports.py:54`) and `SqliteKnowledgeWeigher` implements it by **exact match** of the normalized text against an entity name or alias, counting active `preference` facts times `weight_per_fact`. So it answers "how much do I like *Artist X*", and returns 0.0 for a whole event title like "Artist X - Tour - Venue".
- **Rule (pure, core):** `importance(item, weighers) = max over item.entities with role HEADLINER or SUPPORT of the summed weigher weights for that name`, with support acts discounted by a configured factor; if the item has no entities, fall back to the whole title. The port is unchanged, so no caller of it changes.
- **So extraction must return entities.** `EventCandidate` gains `entities`: headliner and support acts, venue, organizer. Without them the weigher is asked the wrong question. This is the main new requirement on the extractor and its labeled sample.
- **Thresholds are config:** `important_at` (weight at or above which an item is "important") and `watch_list` (the owner's explicit senders and keywords, which set a floor and need no knowledge store). Importance feeds: the lead story, section order by importance, the `IMPORTANT_NEW` alert, and resurfacing of lapsed tasks.
- **Unknown names are surfaced, not guessed.** Names that appear often and have weight 0.0 are listed in "Needs a look" as "artists I do not know", so the owner can add them to knowledge by hand. This app does not write to knowledge in the first release.
- **Name drift:** exact matching means "Artist X (Live)" misses. The fix is entity extraction that returns the clean name, plus aliases in knowledge, not a fuzzy weigher.
- **Tests (against a fake weigher):** headliner weight wins over a support act; a title with no entities falls back to the title; unknown names produce no importance and are listed; the support discount; watch-list floor; importance 0.0 never raises an alert; a weigher that raises is reported and the item is ranked without importance, not dropped.
- **Not researched yet:** how others learn preferences from behavior (done, dismiss, snooze). That would be a later `PreferenceSink` port; the research is still open.

## 14a. Sections and placement

Layout is a pure rule in core, like delivery.

- **`SectionSpec`** (frozen, validated): `id`, `title`, `slot`, `selector` (`kinds`, `tags`, `senders`, `venues`, `window_days`), `order` (`DATE`, `IMPORTANCE`, `MENTIONS`), `limit`, `show_when_empty`. Slots within an edition are unique and gap-free; `EditionConfig.sections` is a tuple of these.
- **`TagRule`** (config): sender, keyword or venue pattern -> tag. `apply_tag_rules(item, rules)` is pure; the extractor's category arrives on `EventCandidate` as a suggested tag with origin `EXTRACTOR`; owner corrections have origin `OWNER` and win.
- **`place(items, sections) -> Layout`**: each item goes to the lowest-slot section whose selector matches; unmatched items go to the fallback section for their kind; an item is never placed twice. `Layout` lists every section, including empty ones, with `show_when_empty` applied at render time, not here.
- **Tests:** an item matching two sections lands in the lower slot only; an unmatched item is not dropped; an empty section keeps its slot number; slots stay stable when another section's content changes; owner tag beats rule beats extractor; a section selector with no criteria is rejected at validation; `limit` reports "and N more" rather than truncating silently.

## 14. Delivery policy: cadence and alerts

Everything about *when to tell the owner* is a pure rule in core, configured by data.

- **`DeliveryConfig`** (frozen dataclass, loaded by `cli`, validated in core): `editions: tuple[EditionConfig, ...]` (each: `name`, `cadence` as `off`, `daily(time)`, `weekly(weekday, time)`, `monthly(day, time)` or `every_n_days(n, anchor)`, `sections`, `look_ahead_days`, `sources`, `max_stories`; names unique; timezone), `triggers` (per trigger: enabled, lead times), `quiet_hours`, `daily_cap`, `watch_list` (senders or keywords the owner marks important).
- **`Event.sale_start`** (optional `ItemTime`): the presale or on-sale moment, kept separate from the event date **[V: gmail-survey, "sale_start (separate field; never start_date)"]**. It is what the `SALE_OPENS` trigger fires on.
- **Pure functions:** `issue_due(edition, now, last_issue) -> bool` (monthly day 31 clamps to the month's last day; a missed run publishes once, never twice) and `plan_alerts(items, now, config, delivery_log) -> AlertPlan`, where each planned alert is `(item_id, trigger, lead, due_at, send_at)` and `send_at` is `due_at` moved out of quiet hours (a `SALE_OPENS` alert inside quiet hours is not moved past its sale time).
- **Ports:** `DeliveryLog` (what was sent or missed per `(item, trigger, lead)`; the idempotency key) and the existing `Notifier` and `Outbox`.
- **Use cases:** `SendAlerts` (plan, drop what the log already holds, enqueue to the outbox, record) and `PublishIssue` (one call per edition, gated by `issue_due`; the issue covers the window since that edition's last issue; `IssueLog` port records each edition's issue number and window). Outcomes are typed: `Sent`, `Deferred(quiet_hours)`, `Capped`, `Missed(too_late)`, `Suppressed(state)`, `NotifierFailed`.
- **Suppression order**, first match wins: item `DONE`/`DISMISSED`/`SNOOZED` -> already logged -> assumed date -> trigger disabled -> too late -> quiet hours -> cap.
- **Importance** is still open **[D]**. Until decided, `IMPORTANT_NEW` is off and the only importance input is the owner's explicit `watch_list`, which needs no model.
- **Tests:** a clock-driven table per trigger and lead; the quiet-hours boundary; a sale opening inside quiet hours; cap rollover into the digest; re-ingest produces no second alert; down for two days then late send versus missed; assumed date never alerts; weekly edition on the wrong weekday is not due; two editions with different cadences keep separate windows and numbers; an item in two editions appears once in each; monthly day 31 in February; DST change on the publish day.

**Exhaustive-outcome rule.** Every use case returns a typed result with one variant per outcome (created, mentioned, rejected with reason, deferred, refused, failed). A test scans every caller in `cli` and the adapters and fails if one discards a result, so a new outcome cannot be silently ignored. "Exhaustive" means every decision and failure path is typed and tested, not that the feature set grows.
