# Concert Tracker

A personal event ledger for live music. It pulls listings from several sources (a ticketing API,
calendar feeds, venue pages), decides which listings are the **same event**, and keeps one record
per event with every source that mentioned it.

It knows nothing about email or newsletters. Mail is just one more source; the project that reads
mail ([last-newsletter](https://github.com/112345brian/last-newsletter)) depends on this one, not
the other way round.

## Use

```bash
uv sync --all-packages
export CONCERT_TRACKER_HOME_TZ=America/Los_Angeles   # times from UTC feeds are shown in this zone

# every command takes --dry-run: real requests, but a throwaway copy of the ledger, counts only
uv run concert-tracker fetch-events --source frequentflyer --days 30 --dry-run
uv run concert-tracker fetch-events --source lodgeroom --days 90
uv run concert-tracker fetch-events --source ical --feed-url https://moshradar.com/calendar/city/los-angeles.ics --feed-name moshradar
uv run concert-tracker events            # what the ledger holds, with the mentions that cite each event
uv run concert-tracker events --json
```

The ledger is `<data dir>/events/ledger.sqlite`, where the data directory is `--data-dir`, else
`$CONCERT_TRACKER_DIR`, else `~/.concert-tracker`. Runs are idempotent: fetching twice changes
nothing, a rescheduled event is updated in place, and an event two sources both list is **one**
event with two mentions.

## Sources

| `--source` | Reads | Needs | Checked against the live service |
| --- | --- | --- | --- |
| `ticketmaster` | Ticketmaster Discovery API | `$TICKETMASTER_API_KEY`, `--city` | **No.** Fixtures are hand-built to the documented shape; the first real `--dry-run` is the check |
| `frequentflyer` | Frequent Flyer LA's JSON API | nothing | Yes |
| `ical` | any published `.ics` calendar | `--feed-url` | Yes (CalDiscovery, Moshradar) |
| `squarespace` | a Squarespace events page (`?format=json`) | `--feed-url`, and `--feed-venue` or `--feed-organizer` | Yes (The Smell, Living Earth, Healing Force) |
| `lodgeroom` | Lodge Room's WordPress API | nothing | Yes |
| `scribble` | the public Sanity API behind Scribble's site | nothing | Yes (mixes music, comedy and workshops: no category field) |

Each adapter's own README (`src/adapter_*/README.md`) records what it reads, what it deliberately
skips, and what was observed live.

**Deliberately not here:** Piqued (answers with a Vercel bot challenge, which this project does not
try to get past), Dice (no public API), Oh My Rockness' show API (needs authentication), and the
LA Events / What's Up In files (the operator requires written permission for bulk ingestion).

**Terms of use are not checked for any source.** Read each one before relying on it, especially for
anything you republish. Frequent Flyer's response says *free with attribution, not for bulk
redistribution*, and the run summary prints the attribution it asks for.

## How "the same event" is decided

A deterministic ladder in `src/core`, tried in order, stopping at the first hit (design:
`docs/design/event-ledger.md`):

1. an iCalendar-style `UID` (a higher `SEQUENCE` updates the event);
2. the same canonical URL;
3. the same normalised title and venue on the **same listed date** (a late-night listing counts as
   the night before);
4. the same date, a related title (one contains the other, or nearly equal) and a shared showtime,
   with no venue conflict.

Otherwise it is a new event, possibly *linked* to look-alikes on the same date (found by a local
n-gram index; an embedding model can be added as an optional extra, see
`src/adapter_embeddings/README.md`). It never merges
across dates (a run of nights is separate events), never merges across a venue conflict, and
errs toward keeping events apart: a missed merge shows a duplicate, a wrong one hides a show.
`src/core/tests/test_dedupe_*` hold labelled same/different pairs, generated invariants, a scale
check, and mutants that the pairs must catch.

## Architecture

```
cli  ->  app  ->  adapters (ledger, n-gram index, one per source)  ->  core  ->  process_lock
```

- **core**: entities, identity, validation and ingest use cases, and the ports (`EventSource`,
  `EventRepository`, ...). No effects at all: no clock, environment, randomness or network.
- **adapters**: each implements a core port and owns its effects. They never import each other.
- **app**: the logic a front end needs, with no front end in it: open the ledger under its lock,
  keep the similarity index in step, show what is stored. It imports core, the ledger and the
  index only (a test enforces it), so another project can vendor it without carrying the sources.
- **cli**: argument parsing, plus the one place that knows which sources exist; reads the
  environment and the clock.

Enforced by import-linter (package edges) and [arborescent](https://github.com/112345brian/arborescent)
(every module in a ring; the inner ring forbidden effects). `make check` runs tests, ruff, ty and
both gates.

A new source is an adapter implementing `EventSource.fetch(window, now) -> SourceBatch`, a branch in
`src/cli/.../fetch_events_command.py`, and tests.

## Development

```bash
uv sync --all-packages
make check          # pytest, ruff check, ruff format --check, ty, import-linter, arborescent
```

`vendor/process_lock` is copied in by [dfetch](https://dfetch.readthedocs.io) from
`112345brian/process-lock`; do not edit it by hand (`uvx dfetch update`).
