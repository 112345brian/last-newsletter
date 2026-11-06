# Mining bripe-job-search for ledger modules

Read-only, 2026-11-06, job repo at `4747cd149`. Importer counts are files that mention the module name (a rough upper bound). Items not read in full are marked [A].

## Already identified earlier (issues #1543 to #1550)
`listing_urgency` + `survival_curve`, `tracker_state`, activity lifecycle, usage budget port, `notify`. Not repeated here.

## New candidates found for the ledger's other needs

| Need | Module | Size | Coupling to cut | Importers |
|---|---|---|---|---|
| Event identity and dedupe | `src/jobsearch/job_dedupe.py` | 126 lines | `JobListing` (fields `id`, `canonical_key`, `resolved_url`, `source`, `digest_identity`, `digest_detail_score`), `source_metadata.is_direct_source`, `state.job_identity.normalize_job_url` | 8 |
| Canonical keys and URL normalization | `src/state/job_identity.py` | 146 lines | `state.text_normalize`, `records.us_states` (job-location specific: `normalize_location`, state abbreviations) | 33 |
| Text normalization kinds (`text`, `space`, `fold`, `words`, `org`) | `src/state/text_normalize.py` | not measured | `org` kind is employer-specific | [A] |
| Date canonicalization at ingestion (relative dates, raw kept, observed-at kept, explicit base so nothing drifts) | `src/jobsearch/posting_dates.py` | 129 lines | external `dateparser`; field names `date_posted*`; `first_iso_date` helper | 4 |
| Deadline alert with cooldown (reads stored data only) | `commands/deadline_alert_cli.py` | 298 lines | imports `digest.mailer`, `job_repository`, `operations`, scoring | [A] |
| Age-based dismissal of stale items | `commands/dismiss_stale_by_age_cli.py` | 398 lines | `job_repository`, `job_activity_repository`, `tracker.helpers`, scoring | [A] |
| LLM deadline extraction | `commands/deadline_extract_cli.py` | 598 lines | browser, page guard, hygiene workflow, scheduler | [A] |

## What matters most

**`job_dedupe` is the same problem as event identity, already solved with a ladder.** It tries id, then a producer-supplied canonical key or resolved URL, then normalized employer + title as the weakest evidence. It also encodes the failure policy the research notes recommended: when a copy could fold into several candidates it is kept as its own row, because showing a duplicate is safe and hiding a live item is not. Direct (employer-board) listings never merge by title; that is the analogue of events whose titles repeat on different dates, so for events the date must join the key.

The ladder maps directly: id -> iCalendar `UID`, canonical URL -> canonical URL, employer + title -> normalized title + local date + venue.

**`posting_dates` solves the "SATURDAY DEC 12, no year" problem class.** It resolves a source value once against the time observed, keeps the raw text for audit, and records when it was observed so a parser change can be re-evaluated. Its caveat for us is year inference across December to January lists, which it does not handle (job boards do not need it) [A].

## Decoupling sketch (not done; nothing in the job repo was changed)

1. `job_dedupe` -> a generic grouping function taking a small `Protocol` (`id`, `canonical_key`, `resolved_url`, `is_direct`, `identity: tuple[str, str]`, `detail_score`) plus an injected URL normalizer. This removes `JobListing` and `source_metadata`. Characterization tests first, per the job repo's strangler policy.
2. `job_identity` -> split the URL and key normalization (generic) from `normalize_location` and the state-name tables (job-specific).
3. `posting_dates` -> split the pure resolver (`value`, `observed_at` -> `date`) from the field-name wrapper; keep `dateparser` as a declared dependency of the extracted package.

The three alert, dismissal and extraction commands are application orchestration with many app dependencies. Read them for design (cooldown, age rule, extraction budget), do not extract.

## Not checked
- Bodies of `text_normalize`, `deadline_alert_cli`, `dismiss_stale_by_age_cli` and `deadline_extract_cli` were only skimmed by their imports.
- Which fields of `JobListing` other callers of `dedupe_jobs` rely on.
- Whether `dateparser` is acceptable in `core`'s dependency set (it would sit outside `core`, in an adapter or a small package).
