# last-newsletter-adapter-frequentflyer

Implements core's `EventSource` port for [Frequent Flyer LA](https://frequentflyerla.com), a
one-person, community-submitted Los Angeles events guide with a keyless JSON API
(`https://frequentflyerla.com/api/v1/events`). Its listings are reviewed before publishing, and
include small rooms that ticketing APIs do not cover.

```bash
uv run last-newsletter fetch-events --source frequentflyer --days 30 --dry-run
uv run last-newsletter fetch-events --source frequentflyer --days 30 --neighborhood echo-park
```

No key or account. `--vibe` defaults to `music`; `--neighborhood` takes a slug such as
`echo-park`.

## Terms: attribution and redistribution

The API states its licence in every response: *Free to use with attribution. Not for bulk
redistribution.* This tool keeps the listings in your own ledger for your own use, which is within
those terms. Two things follow:

- **Attribution** is printed in the run summary, and every mention is recorded with the source
  `frequentflyer`. Anything you *display* from these listings should link back to the listing's
  `frequent_flyer_url`.
- **Redistribution** is not allowed in bulk. Do not publish a dataset or a service built on a copy
  of their listings without asking them first.

## Identity

| Fact | Becomes |
| --- | --- |
| API `id` | `uid` and `message_id` as `frequentflyer:<id>`: the ladder's first rung |
| `ticket_url`, else the guide's own page | `url`: the second rung, so a listing that links to the same ticket page as another source is recognised |
| `venue.name` | the `VENUE` entity (a missing venue is fine) |
| `date` + `start_time` + `timezone` | local date and time; about a third of listings have no time and stay date-only |
| `vibe`, `curation`, `sold_out` | tags |

## Behaviour worth knowing

- There is **no paging**: `offset` and `page` are ignored. A response is complete only if `count`
  equals `total_matching`, so a short response is split into smaller date ranges, and a single day
  that is still short is reported as `truncated`.
- A rate limit of 60 requests is reported in `x-ratelimit-*` headers; a run uses a handful, so
  there is no retry loop. A 429 or a server error stops the run with a clear message and a rerun
  is safe.
- `performers` was empty in every listing observed, so it is not mapped.

## What is verified

The response shape was observed live on 2026-11-09 (field names, formats, the missing-time case,
the ignored paging parameters). The test fixtures are **synthetic** records in that shape, not
copies of their listings.
