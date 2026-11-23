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
export CONCERT_TRACKER_HOME_TZ=Europe/London   # times from UTC feeds are shown in this zone

# every command takes --dry-run: real requests, but a throwaway copy of the ledger, counts only
uv run concert-tracker fetch-events --source ical --feed-url https://calendar.example.com/events.ics --feed-name example
uv run concert-tracker events            # what the ledger holds, with the mentions that cite each event
uv run concert-tracker events --json
uv run concert-tracker backfill-artists --dry-run   # artists from stored titles; lists each change
```

The ledger is `<data dir>/events/ledger.sqlite`, where the data directory is `--data-dir`, else
`$CONCERT_TRACKER_DIR`, else `~/.concert-tracker`. Runs are idempotent: fetching twice changes
nothing, a rescheduled event is updated in place, and an event two sources both list is **one**
event with two mentions.

## Sources

| `--source` | Reads | Needs | Checked against the live service |
| --- | --- | --- | --- |
| `ticketmaster` | Ticketmaster Discovery API | `$TICKETMASTER_API_KEY`, `--city` | **No.** Fixtures are hand-built to the documented shape; the first real `--dry-run` is the check |
| `ical` | any published `.ics` calendar | `--feed-url` | Yes (CalDiscovery, Moshradar) |
| `squarespace` | a Squarespace events page (`?format=json`) | `--feed-url`, and `--feed-venue` or `--feed-organizer` | Yes (The Smell, Living Earth, Healing Force) |

Each adapter's own README (`src/adapter_*/README.md`) records what it reads, what it deliberately
skips, and what was observed live.

Place-specific sources (named venues, a city's aggregators) are not built in: they are plugins
shipped by a client package (see "Source plugins" below), such as a city's own client repository.

**Terms of use are not checked for any source.** Read each one before relying on it, especially for
anything you republish. Some services say *free with attribution, not for bulk
redistribution*, and the run summary prints the attribution it asks for.

## Running every day (Windows)

`concert-tracker run` fetches every enabled source in the catalog (`sources.json`, see
`concert-tracker sources`), records each run in `<data dir>/events/runs.sqlite` and judges each
source's health: **failing** after 3 failed runs in a row, **degraded** after a failed run or when a
usually-busy source suddenly finds under 35% of its usual count. `schedule` runs it daily as a
Windows scheduled task.

```powershell
# 1. API keys live in your user environment, never in the task (set once, then open a new terminal)
setx TICKETMASTER_API_KEY "..."          # only if you use the ticketmaster source

# 2. Look: this prints exactly what would be created and changes nothing
uv run concert-tracker --data-dir $HOME\.concert-tracker schedule install --at 06:30 --home-tz Europe/London

# 3. Create it (running this again changes nothing; a new --at replaces the old time)
uv run concert-tracker --data-dir $HOME\.concert-tracker schedule install --at 06:30 --home-tz Europe/London --yes

uv run concert-tracker schedule status    # is it there, when, and what it runs (read-only; exit 1 if not)
uv run concert-tracker schedule remove    # delete it (nothing to do if it is not there)
```

The task is named `ConcertTracker Run`, runs daily at `--at` (default 06:30) **as you, only while
you are logged on**, and no password or key is given to Task Scheduler. It runs
`concert-tracker --data-dir <dir> run --home-tz <zone> --log --notify` with absolute paths, using
the `concert-tracker` program that is running when you install. Install from the checkout you
intend to keep (its virtual environment is what the task points at); `schedule status` shows the
exact command, and installing from another checkout replaces it. Task Scheduler limits the command
to 261 characters, so a very long `--data-dir` is refused with a message. If the PC is off at the
set time the run is skipped, and the next one is the following day.

**Knowing when a source breaks.** Every scheduled run appends its report to
`<data dir>/logs/run-YYYY-MM.log`, and exits 1 if any source is failing or degraded (Task
Scheduler shows that as the task's last result). A Windows toast says which source and why, once:
a source is announced when it first becomes unwell and again only if it gets worse; it is not
repeated daily, and a source that recovers and later breaks again is announced again. If the toast
cannot be shown (no desktop session) the run says so and tries again next time. The toast uses the
Windows PowerShell that ships with Windows, so it adds no dependency; it has not been seen on screen
in the automated checks.

```powershell
uv run concert-tracker health            # sources that are failing or degraded, with reason and last good run; exit 1 if any
uv run concert-tracker health --json
uv run concert-tracker sources           # every source: last run and health
```

`health` reads the history and always lists every unwell source, whatever was announced before.
It does not notice a run that never happened (PC off for days, task removed): check
`schedule status` and the log's dates for that.

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

## Reading artists out of titles

`concert_tracker_core.title_parsing.parse_title(title)` is a pure function that recognises the
common shapes of a listing title and says which one fired (`TitlePattern`): `"<promoter> presents:
<bill>"`, `"<artist> with|w/ <support>, <support> & <support>"`, `"An Evening with <artist>"`,
`"<artist>: <tour name>"`, `"<a> / <b> / <c>"`, `"<a>, <b>, <c>"` (three or more) and
`"<a> x <b>"`. It also splits off listing noise (`(21+)`, `- Ages 18+`, `- Night 2`, `SOLD OUT`,
`Early Show`) into `decorations`. Every name it returns is a literal piece of the title, and when
no pattern fires nothing is recognised (`pattern` is `NONE`, no names). A recognised pattern is a
reading, not a fact: `"Making Love with David Magidoff"` parses as a band with a guest. The
labelled titles it is tested against, and the known wrong readings, are in
`src/core/tests/fixtures/event_titles.json`.

Ingestion uses it (`title_artists.entities_with_title_artists`): an event no source gave an artist
for gets the headliners and supports its title names (and the promoter, as an organizer). A source's
own artists are never touched, an unreadable title adds nothing, and a venue, a promoter or `TBA`
is never made an artist. `concert-tracker backfill-artists [--dry-run]` does the same for events
already stored; rerunning it changes nothing.

## Making it yours: region directory, plugins, export

The engine is place-agnostic. Three extension points, all additive (nothing changes when none is
used); a client repository (for example one holding a city's venues and scrapers) builds on them.

### Region directory

`--region-dir DIR` (or `$CONCERT_TRACKER_REGION_DIR`; default none) points at one directory of
place-specific data. Layout (every file optional, same shapes as the owner files):

```
region.json        {"name": "Exampleton", "home_tz": "Europe/London"}
venues.json        {"venues": [{"names": [...], "categories": [...], "city": "...", "address": "..."}]}
promoters.json     {"promoters": [{"name": "...", "aliases": [...], "affinities": [...]}]}
sources.json       {"sources": [{"name": "...", "kind": "ical|<plugin>|...", "options": {...}}]}
event_types.json   {"rules": [{"type": "...", <conditions>}]}
```

Precedence, later wins: packaged data < region directory < the owner's files in the data directory
(`--data-dir`). Event type rules of a later layer are tried first. A broken file is an error that
names it; a region directory that does not exist is refused. `region.json` gives the place name
(shown in `export`) and the default `--home-tz` (precedence: `--home-tz`, `$CONCERT_TRACKER_HOME_TZ`,
the region's, then UTC). `schedule install` carries `--region-dir` into the scheduled task.
One loader, `concert_tracker_app.layered_data.load_layered`, reads all four files.

### Source plugins

A package adds sources through the entry-point group `concert_tracker.sources`:

```toml
[project.entry-points."concert_tracker.sources"]
my-sources = "my_package.plugins:PLUGINS"   # one SourcePlugin, or a list/tuple of them
```

The contract (`concert_tracker_core.source_plugins`; core ring, import only that):

```python
class SourceOption:   name: str; help: str = ""; required: bool = False; default: str = ""
class SourceContext:  home_tz: str; environ: Mapping[str, str]
                      http: object | None = None   # an httpx.Client when the engine has one
                      sleep: Callable[[float], None] | None = None
class SourcePlugin(Protocol):                       # runtime-checkable
    name: str                  # lower-case slug [a-z0-9][a-z0-9_-]*: `--source` and a catalog `kind`
    description: str           # one line, shown by `concert-tracker sources`
    options: tuple[SourceOption, ...]
    def build(self, options: Mapping[str, str], context: SourceContext) -> EventSource: ...
    # may raise SourceOptionError; options arrive checked (unknown refused, required present,
    # defaults filled) by resolve_options
# EventSource (concert_tracker_core.event_ports): name -> str;
#   fetch(window: SourceWindow, *, now: datetime) -> SourceBatch(candidates, SourceReport)
#   (raises SourceFetchError)
```

A plugin is used like a built-in: `fetch-events --source NAME --option KEY=VALUE`, a `sources.json`
entry `{"name": "x", "kind": "NAME", "options": {"KEY": "VALUE"}}` for `run`, and it is listed by
`concert-tracker sources`. Built-in names cannot be taken; a plugin that fails to import, is the
wrong shape or reuses a name is reported by entry-point name (in `sources` and in the unknown-source
error) and never stops another source. The engine ships no place-specific source; a client
package registers them
this way.

### Export

```powershell
concert-tracker export --format json --out events.json [--days 60] [--source NAME ...]
concert-tracker export --format sqlite --out events.sqlite
```

Writes the upcoming window for publishing: `schema_version` 1 (JSON Schema:
`concert_tracker_app/data/export.schema.json`, also `concert_tracker_app.export_view.export_schema()`),
`generated_at` (when the ledger last saw any listed event, not the wall clock), `region`, `window`,
`counts`, and per event: id, title, date, all_day, start/end (ISO with offset), showtimes, venue,
city, venue_categories, event_type, sources (names), url, artists (name and headliner/support role),
tags. Unknown is `null`. The same ledger and the same day give the same bytes. It is built from an
allow-list: no Last.fm genres or plays, no message ids, no mail-derived evidence, no local paths
(tests scan the schema, the SQLite columns and the output for these).

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

Genres and listening come from the private `lastfm-taste` library, pinned to a git tag in the
root `[tool.uv.sources]` (a package that depends on the engine must repeat that source).

```bash
uv sync --all-packages
make check          # pytest, ruff check, ruff format --check, ty, import-linter, arborescent
```

`vendor/process_lock` is copied in by [dfetch](https://dfetch.readthedocs.io) from
`112345brian/process-lock`; do not edit it by hand (`uvx dfetch update`).
