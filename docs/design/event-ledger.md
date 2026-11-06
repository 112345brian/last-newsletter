# Event and task ledger: design

Status: draft 1, 2026-11-06. Inputs: `PRODUCT.md`, `docs/research/*.md`.
Tags: **[V]** verified against the repo or by computation, **[A]** assumed, **[D]** decision still open.

## 1. Goal

Add a remembered lane next to the stateless digest. Dated events, deadlines and one-time tasks extracted from newsletters become ledger items with an identity, a date, urgency and the owner's state. News stays stateless, as today.

## 2. The rule that shapes everything: dependency inversion

**Core defines every capability it needs as a port and owns every domain rule. Adapters implement ports. Nothing in core knows a library, a database, a model vendor or a notification service exists.**

Consequences, each enforced by a test rather than by prose:

1. **Core imports the standard library only.** A test parses every module in `packages/core/src` and fails on any import whose top-level name is not in `sys.stdlib_module_names` or `last_newsletter_core` **[V: attribute exists in Python 3.10+; the repo targets 3.11]**. This is stricter than the import-linter contract, which cannot whitelist.
2. **Domain rules live in core, not in an adapter.** What counts as "the same event", how a missing year is resolved, what a default task deadline is, when a task resurfaces and what urgency means are all pure functions in core. A library may help an adapter *produce input* but never decides a rule.
3. **Every port has a hand-written fake in core's tests** (the repo's existing pattern, `core/tests/test_build_digest.py`), and the complete ingest-to-remind flow runs against fakes with no network, no disk and no clock.
4. **One contract-test suite per port**, run against the fake and against each real adapter. An adapter is acceptable when the same suite passes. Swapping SQLite for another store, or Instructor for a raw SDK call, is then a new adapter plus a passing suite, with no core change.
5. **Adapters never import each other** (existing layers contract **[V]**). If two adapters need the same code it moves to a small standalone package below the adapters, like `text_match` and `mailtext`.

## 3. Domain model (core)

All types are frozen dataclasses with no I/O. Datetimes are timezone-aware; constructors reject naive ones.

- **`Event`**: `id` (surrogate, opaque, assigned by the ledger), `kind` (`EVENT`, `DEADLINE`, `TASK`), `title`, `summary`, `when: ItemTime`, `due_is_default: bool`, `state: ItemState`, `mentions: tuple[Mention, ...]`, `first_seen`, `last_seen`, `resurfaced: int`.
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

Match ladder, stop at the first hit, always against open or recently closed items only. Source: `event-prior-art.md` section 6 and `job_dedupe.py`, which uses the same shape.

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
| `UrgencyPolicy` | `band(item, now)` | core default | job-repo `survival_curve` once extracted |
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

1. Architecture: core stdlib-only; the three `pyproject` lists agree; the clock appears only in `cli`.
2. Rules: year resolution (weekday pins the year, the Dec to Jan boundary, ambiguity marked), default due date, resurface once, never after done, past-date rejection, cancellation.
3. Identity ladder: UID update ordering, URL match, title+date+venue match, same title on different dates stays separate, ambiguous stays split and linked.
4. Use cases against fakes: ingest counts, idempotent re-ingest of the same email, state survives re-extraction, cooldown, `Notifier` failure does not lose the reminder.
5. Edge inputs: empty body, NUL characters, partial candidate, duplicate events inside one email, all-day vs timed, an item with no evidence.
6. Port contract suites, run against fakes and, as adapters land, the real ones.

Per the global rule on shared code: before changing `RelevanceWeigher` or `EmailSource`, list every caller first; this design adds ports and leaves those two unchanged.

## 11. Build order (vertical slice)

1. Fix the workspace drift and pick the single type-check command **[V: plain `ty check` has 2 test errors, `packages/*/src` is clean]**.
2. Core: entities, rules, ports, fakes, tests 1 to 3.
3. Core: use cases and tests 4 to 5 on in-memory fakes. At this point the whole design is exercised with zero dependencies.
4. `adapter_ledger` (SQLite) against the contract suite.
5. `adapter_events` with `extruct` and `icalendar` first (no model cost), then the LLM extractor.
6. `remind` command and `Notifier`.
7. Triage page.

## 12. Open decisions and unknowns

- **[D]** Importance source for resurfacing: source count, per-sender weight, or the knowledge weigher (weak on whole titles **[V]**).
- **[D]** Whether title + date + venue is enough for identity; needs a labeled sample from real mail.
- **[D]** Reminder channel: ntfy or the web page.
- **[D]** Shared model-client package versus per-adapter clients.
- **[A]** The share of mail that carries JSON-LD or `.ics` is unmeasured; it decides how much the LLM extractor must do.
- **[A]** Library licenses, current versions and Python 3.11 compatibility for `extruct`, `icalendar`, Instructor, `rapidfuzz` were not verified; none is imported until a session checks them.
- **Not designed here:** the page's visual design (`PRODUCT.md` exists; `DESIGN.md` does not), recurring-event expansion (store the rule, show the next occurrence only), and the job-repo modules, which arrive later as adapters behind `UrgencyPolicy` and identity helpers.
