# Mining bripe-job-search for ledger modules

Read-only, 2026-11-06, measured on `origin/main` `ede0b7c35` (an earlier version of this note used a stale local checkout, `4747cd149`, 25 commits behind). "Foreign imports" below means imports of app packages (`jobsearch`, `state`, `records`, `client`, `digest`, `tracker`, `commands`, `job_repository`) found in the module's source. Items not read in full are marked [A].

## Verdict: what is decoupled and consumable today

| Need | Module (on `origin/main`) | Third-party deps | Foreign imports | Status |
|---|---|---|---|---|
| Urgency bands / survival curve | `libs/urgency` (`item_urgency`, `survival_curve`) | none | none | **ready** |
| Identity ladder + URL normalization | `libs/identity_dedupe` (`ladder`, `url_normalize`) | none | none | **ready** |
| Source date resolution (`observed_at` required) | `libs/source_dates` (`resolver`) | `dateparser>=1.4.3,<2` | none | **ready** (dateparser stays outside `core`) |
| Single-writer lock | `libs/process_lock` | `filelock`, `tenacity` | none | **ready**, adapter-side only |
| Durable outbox (notify without loss) | `libs/durable_outbox` | `process_lock`, `psutil` | none | **ready**, adapter-side only |
| User-state transitions (done, dismissed, ...) | `libs/tracker_state` (`contract`, `user_state_transition`) | none | none | **ready**; check its states against `ItemState` before adopting [A] |
| Notification result type and port | `jobsearch/notification_port.py` (80 lines) | none | none (imports only stdlib) | clean but lives in the app package; copy the shape, do not depend |
| ntfy HTTP transport | `jobsearch/notifications/transport.py` (60 lines) | none | none | clean but lives in the app package |

Install form verified earlier for `identity_dedupe` and `source_dates` (Python 3.11 venv, dry run): `name @ git+https://github.com/112345brian/bripe-job-search.git@<sha>#subdirectory=libs/<name>`. Not tested: `urgency`, `tracker_state`, `process_lock`, `durable_outbox`.

## Decoupled since: commit `3f1d9bf9c` (branch `claude/libs-text-notify-usage-ntfy`, pushed, **not yet on `origin/main`**)

Source-read only (no imports of app packages, `dependencies = []`, `>=3.11`); install not yet tested here.

| Lib | Contents | Pin |
|---|---|---|
| `text_normalize` | generic normalization kinds (`keys.py`) | `text_normalize @ git+https://github.com/112345brian/bripe-job-search.git@3f1d9bf9c26b72dd368edf8a972d57f38628f31f#subdirectory=libs/text_normalize` |
| `notification_port` | `notifier_port`, `transport`, and the pure `ntfy_policy` split out of `ntfy_push` | `notification_port @ git+...@3f1d9bf9c26b72dd368edf8a972d57f38628f31f#subdirectory=libs/notification_port` |
| `usage_ledger_port` | `ledger_port` | `usage_ledger_port @ git+...@3f1d9bf9c26b72dd368edf8a972d57f38628f31f#subdirectory=libs/usage_ledger_port` |

**Superseding decision (owner, 2026-11-06): vendor, do not depend.** This repo is public, so it does not install from the job repo by git URL. The nine libs we want (`urgency`, `identity_dedupe`, `source_dates`, `text_normalize`, `notification_port`, `usage_ledger_port`, `process_lock`, `durable_outbox`, `tracker_state`) are copied verbatim into `vendor/` at `3f1d9bf9c`, with provenance in `vendor/VENDORED.md`. The pin lines above are provenance only. The sections below describe the state before this commit; the first three rows and the `ntfy_push` row are now done.

## Still coupled (need decoupling before we can consume them)

| Need | Where | Why it is coupled | Size |
|---|---|---|---|
| Text normalization (`text`, `space`, `fold`, `words`) | `src/state/text_normalize.py` | imports `state.org_name_noise` for the employer-specific `org` kind; lives under `state`, not a lib | 144 lines, one foreign import |
| LLM usage budget / cost admission | `src/jobsearch/usage_ledger_port.py` | imports `jobsearch.port_not_bound`; port lives in the app package | 48 lines, one foreign import |
| ntfy push with cooldown and restart-retry | `src/jobsearch/ntfy_push.py` | `app_logging`, `state.env`, `process_utils` | 231 lines |
| Age-based staleness rule | `src/jobsearch/staleness.py` | 940 lines over job-specific signals (soft 404, ATS redirects, source traits) | do not extract; reimplement the small age rule in core |
| Deadline alert cooldown | `commands/deadline_alert_cli.py` | CLI orchestration: mailer, repository, scoring | 298 lines; read for the cooldown design only |
| Age dismissal | `commands/dismiss_stale_by_age_cli.py` | CLI orchestration over repositories and workflows | 398 lines; design only |
| LLM deadline extraction | `commands/deadline_extract_cli.py` | browser, page guard, scheduler | design only |

## What this changes in the design

- `UrgencyPolicy`, the identity ladder and date resolution each have a ready implementation. They arrive as **adapters behind core ports**, not as imports in core. Core keeps its own small stdlib default for each, so the ledger runs with none of the libs installed.
- Core's identity normalization stays core code; `identity_dedupe`'s ladder shape is the reference, and a contract test should run the same cases against both.
- Year inference across December to January lists (weekday pins the year) is not in `source_dates` [A]; it stays a core rule.
- Not worth decoupling: `staleness`, the two commands. Their useful part is a rule of a few lines.

## Smallest decoupling asks for the job repo (if we want to consume rather than reimplement)

1. Move `text_normalize` into a lib, with the `org` kind injected or split out (one import to cut).
2. Move `notification_port` and `notifications/transport` into a lib (already import-clean).
3. Move `usage_ledger_port` into a lib (one import to cut).
4. `ntfy_push`: separate the cooldown and retry policy (pure) from logging, env and process restarts.

None of these is required for step 2 of the build order, which is core only.

## Not checked

- Whether `tracker_state` states map onto `ItemState` (`OPEN`, `DONE`, `DISMISSED`, `SNOOZED`, `EXPIRED`).
- Bodies of `ntfy_push` and the deadline-alert cooldown beyond their imports.
- Whether GitHub issues #1543 to #1553 are closed (lookup timed out).
