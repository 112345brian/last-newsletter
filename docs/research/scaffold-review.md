# Event/task ledger: adversarial review of the scaffold plan

Reviewed at `main` = 2a63744. Read-only: nothing in the repo was edited except this file.
Legend: **[V]** verified by reading code or running a command (file:line given);
**[A]** assumed / not checked.

Baseline I measured before reviewing **[V]**: `uv run pytest` 68 passed; `ruff check` clean;
`lint-imports` 1 contract kept; `ty check packages/*/src` clean. **But plain `uv run ty check`
(which also checks tests) reports 2 `invalid-return-type` errors** at
`packages/adapter_knowledge/tests/test_sqlite_knowledge_weigher.py:50` and `:58`. README's
"strict ty all green" holds only for the `packages/*/src` form it documents (README.md "Verifying
this repo"). Pick one command as the gate before adding tests, or the new test files inherit an
ambiguous baseline.

---

## 1. What already exists (reuse before building)

### 1.1 Is `Theme` half an event? Shape yes, role no.

`Theme` (`core/entities.py:31-66`) already carries: `title`, `summary`, `source_message_ids`,
`theme_key` (cross-period identity), `relevant_until: date` (a future date), `first_seen`, `streak`,
`carried_forward`. That *is* most of a dated item with an identity and provenance. Why it still
should not become the ledger entry:

| Needed by a ledger | Theme today | Verdict |
|---|---|---|
| Stable identity | `theme_key: str \| None`, chosen by the LLM, optional (`:61`) | Not deterministic; `None` is legal |
| Start time, tz, all-day flag | only `relevant_until: date` (`:62`) | Lossy: no time, no zone, no "all-day vs timed" |
| Mutable user state | none; `Theme` is `frozen=True` (`:30`) and lives inside an immutable `Digest` snapshot | No update-by-identity at all |
| Survives past one digest | carried only via the *single* preceding same-cadence digest (`build_digest.py:61-73`, `:37-42`) | A daily and a weekly chain never share a theme; one dropped carry loses the date forever |
| Written by anyone | `first_seen` is **never set** outside (de)serialization (grep: only `entities.py:63`, `json_repository.py:34,51`) [V] | Half-wired field; do not build on it |
| Evidence/provenance | `source_message_ids`, but `_verified` silently ignores ids that match nothing (`build_digest.py:92-95`) | OK to reuse the *idea*, not the field |

**Recommendation:** new `Event` entity, not a Theme subclass or extra Theme fields. Keep `Theme` as
the digest's ranking record. Open owner decision (see §5, D3): once a ledger exists there are two
sources of "this has a date" (Summarizer's `relevant_until`, ledger's `Event.start`). The stub
Summarizer hasn't been written yet (`anthropic_summarizer.py:27`), so this is cheap to settle now.

### 1.2 Pieces to reuse as-is

- **Pattern: fakes + injected `today`.** The Summarizer port takes `today: date` rather than
  reading the clock (`ports.py:38-40`); `datetime.now` appears exactly once in the repo, in the CLI
  (`main.py:77`) [V grep]. The ledger/remind use cases must follow: no clock in core. Tests use
  hand-written fakes (`core/tests/test_build_digest.py:12-70`), not mock libs. Copy that.
- **`RelevanceWeigher`** (`ports.py:43-54`) is the right personalization seam for reminder
  priority: `weight_for(candidate: str) -> float`, summed by the caller. Reuse the port; do not add
  a second one. **Caveat [V]:** `SqliteKnowledgeWeigher` matches only when the *whole candidate
  string equals* an entity name or alias (`sqlite_knowledge_weigher.py:44`, `normalize_term` at
  `:80`). An event title like "PyCon US 2026 early-bird deadline" will almost never hit. Expect
  weight 0.0 for most events unless you feed it extracted entity names, not titles. Also its
  docstring says the 3.0 default "mirrors the per-period streak increment" (`:60-65`) but the
  streak increment in ranking is 1 (`build_digest.py:105`) [V]; the comment is stale, so don't
  calibrate urgency against it. And it uses `with sqlite3.connect(...)` (`:86`), which commits but
  does not close the connection (documented Python behavior [A: not run]); fine at N=few, a leak
  if called per event per reminder in a long-lived process.
- **`text_match.normalize_term`** (`text_match/__init__.py:25-44`): NFC + whitespace collapse +
  casefold. It *raises ValueError* on blank, any `Cc`/`Cf` char (this includes NUL and zero-width
  chars), or no `\w` at all (an emoji-only title). The knowledge adapter already catches it and
  returns 0.0 (`:81-84`). **Constraint [V]:** the layers contract puts `core | text_match | mailtext`
  in one row separated by `|` (`pyproject.toml:92`), i.e. independent siblings; README says
  "`core` must never depend on either" (README.md Architecture). So core **cannot** call
  `normalize_term` to build an identity key. Options in D2.
- **`mailtext`**: already used by IMAP (`imap_source.py:23,70-76`). Nothing to add for ledger; the
  extractor receives `EmailMessage.body_text`, already decoded/flattened.
- **`ImapConfig.mailbox`** (`imap_source.py:54`, default `"INBOX"`) is a free newsletter filter:
  point it at a label/folder. The CLI doesn't expose it (`main.py:55-61` passes host/user/password
  only) [V]. One env var (`LAST_NEWSLETTER_IMAP_MAILBOX`) closes blocker B3 without new code in
  the adapter.
- **`JsonDigestRepository`/`DigestRepository` shape** (`ports.py:63-75`): `save` returns an opaque
  slug, `get` returns `None` for unknown. Mirror that style for `EventRepository`; do not reuse
  the JSON store (no identity-keyed update, rewrites whole files).
- **Storage location constant** `_DATA_DIR = ~/.last-newsletter` (`main.py:29`): put
  `ledger.sqlite` there.

### 1.3 What to *not* build

- No new "digest of events" publisher; the `remind` command prints to stdout.
- No second HTML/MIME path; no second normalizer in an adapter (see D2).
- Don't change `Summarizer`, `EmailSource`, `DigestRepository`, or `BuildDigestUseCase`'s
  constructor. The plan is purely additive, so the "grep every caller" rule in your global
  CLAUDE.md is satisfied trivially: callers of `BuildDigestUseCase(...)` are `cli/main.py:64` and
  `core/tests/test_build_digest.py` only [V grep not run for tests dir; A].

---

## 2. Where the ledger lives under import-linter

### 2.1 Placement

Contract (`pyproject.toml:86-93`) is three layers: `cli` > {all adapters, siblings} > {core,
text_match, mailtext}. Siblings in a `|` row may not import each other.

- **Entities, ports, use cases, urgency function → extend `core`.** `Event`, `EventState`,
  `EventExtractor`, `EventRepository`, `IngestEventsUseCase`, `ListRemindersUseCase`,
  `urgency()`. All pure; no new dependency. (Urgency is policy, like `_rank_key`
  `build_digest.py:102-106`.)
- **SQLite repository → new package `adapter_ledger`** (not `adapter_storage`: that package's
  README/identity is "flat JSON digests"; mixing both would make an adapter that implements two
  unrelated ports. Not enforced by the linter either way [A]).
- **LLM extractor → new package `adapter_events`** (or inside `adapter_summarizer`; see D4).
  Adapters cannot import each other [V contract], so a shared Claude client cannot live in
  `adapter_summarizer` and be imported by `adapter_events`. It must be a standalone generic
  package (like `text_match`/`mailtext`, e.g. `llm_json`) or be duplicated. This is the
  single biggest structural decision (D4) because the first real LLM adapter is also unwritten.
- **Wiring → `cli`**: `remind` and `extract` (or `ledger`) subcommands in `main.py` (currently a
  hand-rolled `argparse` with `build`/`serve`, `:95-108`).

### 2.2 The linter trap: a new package is invisible until registered

Three hand-maintained lists must each get the new package: `[tool.uv.workspace].members`
(`pyproject.toml:18-30`), `root_packages` (`:73-84`), and the `layers` row (`:89-93`). Forgetting
`root_packages` means the package isn't analysed at all (import-linter only checks listed roots
**[A: not run; standard import-linter behavior]**). The repo has *already* drifted: `members` lists
`packages/libraries` which does not exist **[V: `ls packages/libraries` → No such file]**. (Odd but
verified: `uv lock --check` and `uv run pytest` still succeed with that stale member, so it's
silent, not loud.) **Write a test first** (§2.4 T0) that globs `packages/*` and asserts each dir
appears in all three lists, and that every `members` entry exists.

### 2.3 Entities and ports (sketch, not code)

- `Event(key: str, title: str, kind: EventKind{EVENT,DEADLINE,TASK}, when: EventTime, summary,
  source_message_ids, first_seen_at: datetime, last_seen_at: datetime)`.
- `EventTime`: either `AllDay(date)` or `Timed(start: datetime(aware), tz_name: str,
  end: datetime|None)`. Construction rejects naive datetimes and unknown IANA names.
- `EventState`: `OPEN | DONE | DISMISSED | SNOOZED(until: datetime)`, stored **separately** from
  extraction fields (D6).
- `EventExtractor.extract(messages, *, now: datetime, home_tz: str) -> list[EventCandidate]`.
  `EventCandidate` is untrusted LLM output (partial allowed); the use case turns candidates into
  `Event`s or rejects them. Mirrors the `_verified` principle at `build_digest.py:80-99`: derive
  what's mechanical, don't trust the model.
- `EventRepository.upsert(event) -> UpsertResult(created|updated|unchanged)`, `list_open(...)`,
  `set_state(key, state, at)`, `get(key)`. Return a result object, **and** add the
  scan-the-callers test required by your CLAUDE.md so no caller discards it (T9).

### 2.4 Minimal vertical slice and tests-first list

Slice: fake `EmailSource` → `IngestEventsUseCase` → fake `EventExtractor` → real SQLite repo →
`ListRemindersUseCase` → `remind` prints. Real LLM and real IMAP are *out* of the slice (they are
blockers B1/B3, not part of proving the ledger).

Tests, in the order to write them (all fail first):

- **T0** workspace registration test (§2.2).
- **T1** `Event`/`EventTime` validation: naive datetime rejected; bad tz name rejected; all-day
  has no time; `end < start` rejected; empty/blank/NUL-containing title rejected.
- **T2** `event_key`: same event, trivial wording/case/whitespace/NFC differences → same key;
  different dates → different key; emoji-only/blank title does not crash (cf. `normalize_term`
  ValueError); NUL stripped, not split.
- **T3** `urgency(event, now, home_tz)`: overdue > due today > due soon > far; all-day on *local*
  today is "due today" (not overdue); timed event 1 min ago is past; DST-boundary day; snoozed and
  done/dismissed are excluded; table-driven.
- **T4** `IngestEventsUseCase` with fake extractor: new events created; re-run same input →
  `unchanged`, no duplicate rows; user state preserved across re-ingest (the "publish before
  save"/same-window rerun hazard, `main.py:75-76`); two candidates with the same key in one email
  → one event, both provenance ids kept.
- **T5** candidate rejection: hallucinated date in the past beyond grace → rejected with reason
  (not silently dropped); cited message id that matches no fetched message → provenance dropped
  and event kept only if ≥1 verifiable id (same rule as `_verified`).
- **T6** `SqliteEventRepository` contract tests (run the same suite against an in-memory fake):
  round-trip aware datetime with offset; NUL in text (SQLite stores NUL via bound parameter, but
  `length()` and C-string functions truncate — **verified**: `length`=2 for `"ab\0cd"`, equality
  with the full value matches; `LIKE`/FTS would be unreliable), so strip NULs at the entity
  boundary rather than rely on the DB; concurrent writers (`busy_timeout`); transaction rollback
  on second-attempt failure leaves prior rows intact; connection closed.
- **T7** `ListRemindersUseCase`: ordering, limit, snooze expiry returns the item, dismissed never
  returns even if the date changes (policy D7), empty ledger → empty list, not an error.
- **T8** CLI: `remind` with `--today` / injected clock; no network; exit code 0 on empty.
- **T9** caller-scan test: every call to `EventRepository.upsert` in `packages/**` uses its
  return value (AST scan), per global CLAUDE.md.

---

## 3. Blockers inside the repo (ranked by how badly they break the slice)

**B1. The only LLM adapter is a stub [V].** `AnthropicSummarizer.summarize` raises
`NotImplementedError` (`anthropic_summarizer.py:27-28`) and `adapter_summarizer` has **no tests
dir** [V file list]. The ledger's `EventExtractor` is a *second* LLM adapter. With a fake, the
slice proves the ledger, not extraction. Say that explicitly in the plan so a green test suite
isn't read as "events work". Also: two LLM calls over the same inbox doubles tokens; if one
call could return themes+events, decide before writing the first prompt (D4).

**B2. Privacy: the IMAP source ships the entire inbox to whatever consumes it [V].**
`conn.search(["SINCE", since.date()])` then `fetch(..., ["RFC822"])` for every hit
(`imap_source.py:112-115`), no sender/List-Unsubscribe/folder filter. Bodies go to the Claude API
in the future adapter. Receipts, 2FA codes and personal mail would be extracted into a reminder
DB. Cheapest fix: dedicated mailbox/label (§1.2). Better: a `List-Id`/`List-Unsubscribe` header
check in `_to_email_message`. Either way **before any real extractor runs**.

**B3. Missing `Message-ID` becomes `""` [V]** (`imap_source.py:72`: `msg.get("Message-ID", "")`).
Provenance for an event is `source_message_ids`; empty ids collide in `_verified`'s dict
(`build_digest.py:92`) and in any `(key, message_id)` uniqueness constraint. Need a deterministic
fallback id (hash of sender+date+subject) before the ledger records provenance. Test it.

**B4. Time zones: the existing code answers "what is today" in UTC [V].**
- CLI: `until = datetime.now(tz=UTC).replace(hour=0...)` (`main.py:77`); window is UTC midnight to
  UTC midnight.
- Use case: `today = request.until.date()` (`build_digest.py:134`), i.e. the UTC date of the
  window *end*, passed to the summarizer and `_still_eligible`/`_rank_key` with `>= today`
  (`:58`, `:103`).
- **Demonstrated** (ran Python): at 21:30 America/New_York on 2026-11-05 the UTC date is
  2026-11-06, so `today` = Nov 6. A deadline of Nov 5 (still today for the user) is treated as
  expired and dropped from eligible carry-forward.
- `Theme.relevant_until` is a bare `date` with no zone, so an LLM-extracted "Nov 5" is
  interpreted in whatever zone the code happens to use.
Required for the ledger: a single `home_tz` setting (IANA name; default from the machine's local
zone), `today` for reminders computed as `now.astimezone(home_tz).date()` and **injected** (never
read in core), all-day events compared by local date, timed events compared as aware instants.
Do not "fix" `main.py:77` as part of this scaffold; it governs digest windows and re-run slugs
(`:75-76`), so changing it alters `digest_slug` identity (`entities.py:81-86`; the slug also
formats `period_start` without its offset, so two windows with different offsets could collide
**[A: not exercised]**). Keep the digest on UTC and give `remind` its own clock/tz (D5).

**B5. Naive vs aware datetimes [V].** Python raises `TypeError: can't compare offset-naive and
offset-aware datetimes` (ran it). The IMAP adapter protects the existing path by dropping naive
`Date` headers (`imap_source.py:66-69`); an LLM-extracted datetime has no such guard. `Event`
must refuse naive datetimes at construction (T1) and the SQLite adapter must store ISO-8601 text
with offset (not sqlite3's implicit adapters).

**B6. Non-atomic writes can brick `build` [V chain].** `JsonDigestRepository.save` uses
`path.write_text` (`json_repository.py:90`), as does `MarkdownPublisher.publish`
(`markdown_publisher.py:~49`). `BuildDigestUseCase.execute` calls `list_recent` first (`:136`),
which `json.loads` every file with no per-file error handling (`json_repository.py:95`). A crash
mid-write leaves truncated JSON and every later `build` raises until you hand-delete it. This does
not block the ledger slice (SQLite transactions are atomic) but it *does* matter if you wire
`extract` into `build`. Keep ledger ingest a separate command/use case, and fix the JSON write
(temp file + `os.replace`) as its own change with its own test.

**B7. `publish` runs before `save` [V]** (`build_digest.py:164-165`). Publish failure means no
saved digest, so no streak continuity and a retry re-ingests. For the ledger the equivalent hazard
is "ledger saved, digest not": make ingest idempotent by key (T4) and don't put it inside the
digest transaction.

**B8. Stale workspace member** `packages/libraries` (`pyproject.toml:27`) [V] and the README
status text "68 tests / ty green" (README.md Status) are slightly off (see the baseline note at the top). Fix first (T0).

**B9. `Open Last Newsletter.command` and `serve`** are read-only over digests (`adapter_web`
depends on `DigestRepository` only). The ledger has no UI in the slice; don't extend `adapter_web`
in this scaffold. [A: not read in detail.]

---

## 4. Edge inputs the extractor (and the use case behind it) must survive

Each is one table-driven test at the use-case level (fake extractor returns the bad candidate) and,
when the real extractor exists, one parsing-layer test on raw model output.

| Input | Expected behaviour |
|---|---|
| No messages / empty body (`mailtext` returns `""` when no text part, `mailtext/__init__.py:64`) | Extractor not called or returns `[]`; no error; `remind` still works |
| Body is only HTML boilerplate / huge (no size cap exists today [A: grep found none]) | Truncate to a documented byte budget in the *adapter*; test the cap |
| NUL / control chars in title or summary | Strip at `Event` construction; `normalize_term` would raise `ValueError` on them (`text_match:38`), so key derivation must not call it unguarded |
| Emoji-only or digits-only title | Key derivation still works (emoji-only makes `normalize_term` raise at `:41-43`) |
| Partial object (missing `title`, `date` null, `date` string "next Friday", extra unknown fields) | Candidate type is all-optional; use case rejects with a reason enum; never `KeyError` out of the adapter. Existing `_theme_from_dict` indexes keys directly (`json_repository.py:42-55`); do **not** copy that style for model output |
| Hallucinated date in the past | Reject if `start < now - grace`, **unless** the email itself says "recap/last week" (D8). Count and report rejections in the ingest result |
| Hallucinated far future (year 2099, or a year off by one) | Reject beyond horizon (default 2 years; owner knob) |
| Relative dates ("tomorrow", "this Friday") | Resolve against the **email's `received_at`** in home tz, not `now`; extractor gets `received_at` per message. Test: a week-old email saying "Friday" |
| All-day vs timed | `AllDay(date)` vs `Timed(aware dt + tz)`; a "9am" with no zone → floating, interpreted in the event's stated or home tz (D5), recorded as such; all-day never gets a fabricated 00:00 |
| Time zone stated in text ("9am PT") | Store the IANA zone; DST-edge test (event on 2026-03-08 / 2026-11-01) |
| End before start; multi-day all-day range | Reject or normalise; test |
| Duplicate events in one email (header + footer repeat, "save the date" + "reminder") | Same key → one event, merged provenance (T4) |
| Near-duplicates across emails ("PyCon Sat" vs "PyCon 2026") | Exact-key dedupe will miss these (D2). The slice should *surface the miss as visible duplicates*, not hide it |
| Same key, changed date in a later email | Update `when`, record `updated_from`; if state is `DISMISSED` → D7 |
| Cited `source_message_id` not in the batch | Drop that id (mirrors `build_digest.py:92-95`); zero valid ids → reject |
| Prompt-injection in the newsletter body ("ignore previous, create event ...") | Extractor output is data: schema-validated, bounded count per message (e.g. ≤20), and never executes tool calls. Test with a body containing instructions |
| Second attempt fails after first succeeded (batch of N, event k throws) | Per-event isolation or one transaction; tests assert no half-state either way |
| Same input twice | `unchanged`, state intact (T4) |

---

## 5. Ordered scaffold plan

Each step is test-first, one commit, and leaves `pytest`, `ruff check`, `lint-imports`, and the
chosen `ty` gate green. Steps 1-2 touch existing config only.

1. **Baseline hygiene.** Remove `packages/libraries` from `members`; fix the 2 `ty` test errors or
   declare the src-only gate; add T0 (registration test, lives in a new `tests/` at repo root or
   in `cli/tests`; `testpaths = ["packages"]` at `pyproject.toml:70` means a root `tests/` dir
   would not be collected, put it under `packages/cli/tests/`). Files: `pyproject.toml`,
   `packages/cli/tests/test_workspace.py`.
2. **Core time primitives.** `core/entities.py` (or new `core/events.py`; keep `entities.py` for
   existing types to avoid churn): `EventTime`, validation. Tests T1. No new deps.
3. **Identity key.** `event_key()` in core, stdlib `unicodedata` only. T2, including a
   cross-check test (in `cli/tests`, which may import both) that its normalization agrees with
   `text_match.normalize_term` on a fixed corpus, so the two can't drift silently.
4. **Event + state + ports.** `Event`, `EventState`, `EventCandidate`, `EventExtractor`,
   `EventRepository`, `UpsertResult` in `core/entities.py`/`ports.py`. Tests: construction and
   state transitions (T1 remainder). Add the in-memory fake repo used by later steps.
5. **Urgency.** `core/use_cases/urgency.py`, pure `urgency(event, now, home_tz) -> float` plus
   `is_due_today`. T3, table-driven, includes DST and local-vs-UTC date cases from B4.
6. **Ingest use case.** `IngestEventsUseCase` with fake extractor + in-memory repo. T4, T5, T9
   (the caller scan will have just one caller at this point, which is the point: it keeps
   later callers honest).
7. **Reminders use case.** `ListRemindersUseCase` (+ optional `RelevanceWeigher`s, default none,
   the `BuildDigestUseCase` pattern at `build_digest.py:113-131`). T7.
8. **SQLite adapter.** New `packages/adapter_ledger/` (pyproject modelled on
   `adapter_storage/pyproject.toml`: depends only on `last-newsletter-core`, workspace source).
   Register in `members`, `root_packages`, `layers` row. Run the repository contract tests
   (T6) against both fake and SQLite. Schema with `PRAGMA user_version` (same discipline the
   knowledge weigher expects of its DB, `sqlite_knowledge_weigher.py:35`), `with conn:`
   transactions + explicit `close()`, ISO text datetimes, `UNIQUE(key)`, separate `event_state`
   table, `event_source(key, message_id)` provenance table.
9. **CLI wiring.** `remind` (and `extract`) subcommands; `--today`/`LAST_NEWSLETTER_HOME_TZ`
   injection; `LAST_NEWSLETTER_IMAP_MAILBOX`. T8. Keep `build` untouched.
10. **Message-ID fallback + mailbox filter** in `adapter_email` (B2, B3) with tests in
    `adapter_email/tests/test_imap_source.py`. Do before step 11.
11. **Real extractor adapter** (D4) with recorded-response fixtures for parsing tests; network
    never in tests (README states "fakes only", README.md Verifying). Shares/gets the Claude
    client with the Summarizer decision.
12. *(Separate changes, not in the scaffold.)* Atomic JSON writes (B6); publish/save order (B7);
    implement `AnthropicSummarizer`.

---

## 6. Decisions the owner must make

- **D1. Ledger scope.** One "event" concept with `kind` (event/deadline/task), or events only
  and tasks later? Tasks have no date often, which breaks `EventTime` as required.
- **D2. Identity and dedupe.** (a) Deterministic key = normalized title + date (+ kind), exact
  only; (b) key chosen by the LLM against candidates from the ledger (like `prior_themes`),
  fuzzy but non-deterministic and costs a second prompt. And where does normalization live: a
  small duplicate in core (recommended; stdlib only) vs. relaxing the contract so core may import
  `text_match` (contradicts README).
- **D3. Single source of truth for dates.** After the ledger exists, does the Summarizer still set
  `Theme.relevant_until`, or does the digest read the ledger? Affects the unwritten prompt.
- **D4. LLM structure.** One call returning themes+events vs two ports/two calls; and the shared
  Claude client's home (standalone generic package vs duplicated vs `adapter_events` absorbing
  `adapter_summarizer`). Also the cost cap per run.
- **D5. Time semantics.** `home_tz` source (env var vs system zone); how a floating "9am" is
  stored; whether `build`'s UTC-midnight windows stay as is (recommended: yes, untouched).
- **D6. User state model.** State lives in a separate table and survives re-extraction
  (recommended) vs on the event row. Is `DONE` per event or per occurrence (recurring events)?
- **D7. Dismissed/done and changed facts.** If a dismissed event's date changes in a later
  email: stay dismissed, or resurface? Snooze semantics (until instant vs until local date).
- **D8. Past-date policy.** Grace window; how to treat recaps/"last week" content; the maximum
  future horizon.
- **D9. Privacy gate.** Dedicated mailbox/label vs header heuristics vs sender allowlist; and
  whether any non-newsletter body may ever reach the API.
- **D10. Trigger model.** `remind` as a foreground command only (consistent with README's
  "no daemon" stance) vs a launchd/cron job vs a notification. The scaffold assumes foreground.
- **D11. Quality gate.** `ty` on src only vs all (see the baseline note at the top), and whether to fix the 2 existing test
  errors in step 1.

---

## 7. What I did not verify

- Whether import-linter silently ignores a package missing from `root_packages` (standard
  behavior, not run). Cheap to confirm in step 1 with a throwaway package.
- `uv`'s exact behavior with the missing `packages/libraries` member (observed: no failure).
- Repo-wide absence of an input-size cap in any adapter (I read every adapter source file but did
  not grep exhaustively for a cap).
- `adapter_web`, `adapter_publish` tests, and `Open Last Newsletter.command` were skimmed for
  structure only.
- Nothing was run against a real IMAP server, Claude API, or `knowledge.db`.
