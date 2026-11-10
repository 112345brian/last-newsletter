# last-newsletter-adapter-venues

Implements core's `EventSource` port for rooms that publish a JSON feed of their own and that do
not fit a generic format. One small module per venue; all share one `httpx` client
(`client.py`: status checked, body capped, errors that name the status or exception type and never
a URL). Adding a venue is a module here, a branch in the CLI, and a test file.

| Source | Venue | Feed |
| --- | --- | --- |
| `lodgeroom` | Lodge Room, Highland Park | its WordPress REST API, `/wp-json/wp/v2/shows` |
| `scribble` | Scribble, Highland Park | the public Sanity content API behind its own website |

```bash
uv run last-newsletter fetch-events --source lodgeroom --home-tz America/Los_Angeles --days 90 --dry-run
uv run last-newsletter fetch-events --source scribble  --home-tz America/Los_Angeles --days 90 --dry-run
```

Neither needs a key or any other flag; times are shown in `--home-tz`.

## Lodge Room

- The endpoint lists **every show ever** (393 when checked, 100 per page) ordered by when the
  *listing* was published, not by show date, so all pages are read (4 requests, about 2.4 MB, with
  a pause between pages) and upcoming shows are picked out here.
- The show date is `acf.date_and_time_of_show`, written `11/18/2026 7:00 pm` in the venue's own
  time. The top-level `date` is the publish date and is never used.
- Artists are nested records: `headliner` becomes `HEADLINER` entities, `additional_artists`
  `SUPPORT`, and the venue record the `VENUE`. Door time goes at the front of the summary, `ages`
  becomes the age, and `genre` a tag. A ticket or RSVP link is the `url` when there is one,
  otherwise the show's own page.
- Consecutive nights of one act stay separate events (core models one event per date).

## Scribble

- The venue's own website reads its programme from a public Sanity content API, and this reads the
  same one. It is the site's CMS query endpoint, not a published API: no stated terms, no stability
  promise, and it can change without notice. Read it gently (one request, a page of 100).
- `date` is a UTC instant and is shown in the configured zone, which can change the date (03:30Z is
  7:30 pm the evening before).
- **The programme mixes music, comedy and workshops and has no category field**, so nothing here
  can tell them apart: every upcoming event comes through.
- There is no venue field (Scribble is the venue), no ticket link, and the public page address is
  not in the data, so events carry no `url`.

## Behaviour common to both

Every skip is a counted reason in the run summary (`no_id`, `no_title`, `bad_date`), events outside
the requested dates are counted, and `evidence` is built from the title, date, time and venue so a
rerun is *unchanged* and a reschedule is recorded and applied.

## What is verified

Synthetic payloads in the observed shapes cover every rule above, and both were run live through
the CLI as dry runs: Lodge Room gave 60 shows in a 120-day window (333 more were past or later), all
with a time and an age, 61 headliners and 52 supports; Scribble gave 21 events.

## Not here: Piqued

Piqued (`piqued.fm/api/events`) answered HTTP 429 with a **Vercel Security Checkpoint**, a bot
challenge that needs JavaScript, so it is not read. Getting past that would mean imitating a
browser, which this project does not do. If the operator allows automated reads (an API key, or a
request to lift the challenge for this client), a module here is the place.

Whether a venue's terms allow your use is not checked. Read them before relying on a feed,
especially for anything you republish.
