# Can last-newsletter consume the job repo's machinery?

Investigated 2026-11-05, read-only. Job repo at `4747cd149`, last-newsletter at `2a63744`.
Tags: **[V]** verified (command or file named), **[A]** assumed.
The owner wrote all of this code, so licensing and permission are not questions here. This is only about how each library can be consumed.

> **Superseded in part, 2026-11-06.** This note measured `4747cd149`, which was 25 commits behind `origin/main` (`ede0b7c35`). Urgency, identity and date logic are now installable libs (`libs/urgency`, `libs/identity_dedupe`, `libs/source_dates`). See `job-repo-mining.md` for the current state; statements below about those three being "not consumable" are out of date.

## Answer

Four of the nine candidates can be consumed today as pinned git dependencies on the owner's machine: `llmhost`, `evalkit`, `text-claims` and `collection_core` (a monorepo subdirectory). They each have a repo and a `pyproject.toml` with a `>=3.11` floor [V]. The other five (`tracker_state`, `records`, `process_lock`, `durable_outbox`, and the urgency pair) exist only inside the job repo, so they need extraction first (#1506, #1543) or a vendored copy. Recommendation: **no imports now; define our own ports in `core`. Once extracted, use pinned git dependencies.**

One neutral line: others cannot install from the private repos [V: anonymous `git ls-remote` is refused, authenticated `ls-remote` from this machine succeeds for all five repos], so a clone by someone else would not resolve them until the repos are public.

## 1. How each candidate can be consumed today

| Candidate | Source [V: `devtools/vendored.lock.json`, `ls libs vendor`] | Package metadata [V: pyproject files] | Third-party deps | Consumable today |
|---|---|---|---|---|
| llmhost | own repo `112345brian/llmhost`; vendored at `880affbfa6`, repo HEAD is now `1a3c60a` | `llmhost` 0.2.0 (local clone), hatchling, `>=3.11`, no license field | pydantic>=2.13, requests>=2.33, genai-prices>=0.2.1; optional extras `claude`, `codex`, `all` (anthropic, claude-agent-sdk, openai-codex) | **git dependency**: `llmhost @ git+https://github.com/112345brian/llmhost@<sha>` [A: not installed in a test run] |
| evalkit | own repo `112345brian/evalkit`; vendored at `ada23b949b`, HEAD is now `6df5679` | `evalkit` 0.1.0, hatchling, `>=3.11` | none | **git dependency**, never a bare name: PyPI `evalkit` is someone else's package (HTTP 200) [V: `curl pypi.org`] |
| collection_core | subdir `packages/collection-core` of `scraper-shaper`; vendored at `8582f52864`, HEAD is `d029f91` | `collection-core` 0.1.0, `>=3.11` | none (stdlib imports only) | **git dependency with `subdirectory=`** [A: standard uv/pip syntax, not run] |
| tracker_state | `libs/tracker_state`, job repo only (no repo of its own; #1550, #1506) | `tracker-state` 0.0.0, `>=3.11` | none (440 LOC) | job-repo git subdirectory, or vendored copy; cleaner once #1506 gives it a repo |
| records | `libs/records`, job repo only | `records` 0.0.0, `>=3.11` | json5>=0.14,<0.15 | same; PyPI `records` is someone else's package [V] |
| process_lock | `libs/process_lock` | `process-lock` 0.0.0, `>=3.11` | filelock, tenacity (114 LOC) | same |
| durable_outbox | `libs/durable_outbox` | `durable-outbox` 0.0.0, `>=3.11` | psutil, `process_lock` (394 LOC) | same; needs `process_lock` too |
| listing_urgency | `src/jobsearch/listing_urgency.py` (94 lines), inside the app, no package | none | stdlib + `survival_curve` | **not consumable**; needs extraction (#1543) or a copy |
| survival_curve | `src/jobsearch/survival_curve.py` (128 lines) | none | stdlib only | same |

Other facts:
- **Python floor:** every `pyproject.toml` says `>=3.11` [V]. The job repo root is `>=3.11,<3.13` and its CI runs 3.12 only [V: `.github/workflows/ci.yml`], so 3.11 is declared but untested there [A: likely fine, plain stdlib].
- **The job repo vendors; it does not depend.** Its copies have no pyproject; they sit under `vendor/<lib>/src` on `pythonpath` and the root declares their third-party deps itself [V: root `pyproject.toml` comment "a vendored copy brings no dependencies of its own"]. Each lib's files are pinned by SHA-256 in the lock, written only by `devtools/vendored_sync.py` [V].
- **Git dependency precedent:** the job repo already uses `io-policy-engine @ git+https://github.com/112345brian/io-policy.git@v0.3.0`, and `arborescent` by `rev=<sha>` [V].
- **Most libs have no tag or version discipline yet:** `0.0.0` for the four `libs/` members [V]. A git dependency would pin a SHA.
- **Urgency fit:** `listing_urgency` reads only `closing_date` and `date_posted`/`first_seen_at` from its mapping [V: lines 71, 77]. `OPEN_ENDED_CURVE` is calibrated on 54 job listings and marked PROVISIONAL (#1543), so for events only the `SurvivalCurve` class and the stated-date step logic carry over.

## 2. Consumption options

| Option | What it takes | Fits |
|---|---|---|
| A. Pinned git dependency | a `[tool.uv.sources]` entry per lib; lib needs its own repo or a subdirectory path | llmhost, evalkit, text-claims, collection_core now; the `libs/` members after extraction |
| B. Vendored copy with a lock | our own sync script and scanner (the job repo's are `vendored_sync.py` and `vendored_lib_scan.py`); we declare the deps | any; heaviest to maintain, and fails our lint unless excluded (section 4) |
| C. Copy small stdlib-only code | rewrite to our standards, add tests | the urgency pair (222 lines) only |
| D. Own ports in `core`, adapters later | design work now | everything, since nothing has to be installed |
| E. Published package (PyPI or a public repo) | publishing and naming work | later; a collision on `evalkit` and `records` means distinct names are needed |

## 3. Realistic now vs after #1543–#1550

| Candidate | Now | After |
|---|---|---|
| llmhost | A works. But we already have `adapter_summarizer`, and llmhost adds pydantic, requests and genai-prices to the workspace | A; #1545 concerns the job app's budget policy, not llmhost |
| evalkit | A works; not needed by a newsletter pipeline [A] | A |
| collection_core | A works (subdirectory); source outcomes and run health could map to our fetch loop [A] | A |
| tracker_state | job-repo git subdirectory or B; or D | A via #1506 (own repo) |
| records / process_lock / durable_outbox | D | A after extraction; `durable_outbox` needs `process_lock` first |
| listing_urgency + survival_curve | C or D | A via #1543 |

Smallest set usable now: **none imported.** First candidates once ready: `tracker_state` for dismissed/completed user-intent state, then the urgency pair. `collection_core` and `llmhost` are consumable now but have no current need.

## 4. Would our config accept each option?

Evidence from a scratch copy of last-newsletter (not the real repo; in the session scratchpad). I copied `listing_urgency`, `survival_curve`, `tracker_state` and `evalkit` in verbatim as workspace packages, then ran the repo's own tools:

- **ruff** (`select = ["ALL"]`): **357 errors** on verbatim code [V]; `ruff format --check`: 19 of 20 files would be reformatted [V]. Option B or C needs an `exclude` or `per-file-ignores`, or a rewrite.
- **ty** (strict, `error-on-warning`): **28 diagnostics**, e.g. bare `Mapping` in `listing_urgency` [V].
- **import-linter:** new roots go in `root_packages`. Putting them in the bottom layer alongside `core | text_match | mailtext` passes [V]. A `core` to `tracker_state` import is **rejected** when they are siblings in that layer [V]. For `core` to use a library, give libraries a layer below `core`.
- **Option A:** installed packages are not linted by ruff or ty, so it avoids the 357+28 diagnostics. To constrain them with import-linter, add their root package names [A: external packages are not checked by import-linter unless listed; not tested].
- **Option D:** passes by construction.
- Workspace `pyproject` changes needed for A or B: add the third-party deps (for llmhost: pydantic, requests, genai-prices) [V].

## Decision

**Recommendation:** do not import job-repo code yet. Define ports in `core` (urgency ranking and user-intent state) with small own implementations. When #1506 and #1543 land, add the extracted libraries as pinned git dependencies (option A), in a new layer below `core`. If a library is needed before extraction, use `tracker_state` as a git subdirectory dependency rather than a vendored copy, because it has no deps and our lint rules reject verbatim vendored code.

## Not checked

- No install was run: an actual `uv add git+…` of `llmhost` or the subdirectory form was not tried.
- `llmhost` version at the pinned commit (only the local clone's 0.2.0 was read).
- Behavior on Python 3.11 for any candidate.
