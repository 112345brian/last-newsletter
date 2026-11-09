# last-newsletter-adapter-ticketmaster

Implements core's `EventSource` port against the Ticketmaster
[Discovery API v2](https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2):
music events for a city and a window of dates, mapped to event candidates and fed through the same
identity ladder as email.

## Using it

```bash
export TICKETMASTER_API_KEY=...          # free key: https://developer.ticketmaster.com
uv run last-newsletter fetch-events --city "Los Angeles" --region CA --days 60 --dry-run
uv run last-newsletter fetch-events --city "Los Angeles" --region CA --days 60
```

`--dry-run` makes the real API calls (they count against your quota) but works on a throwaway copy
of the ledger and prints counts only. Without it the events are written to the ledger, the same
one `process` writes, so an event already known from a newsletter is **cited**, not duplicated.
`--dma-id 324` widens a search to the whole Los Angeles market instead of the single city.

Nothing is read from or written to anywhere but `<data dir>/events/`. The key is read from the
environment only; it is never written to disk, printed, or included in an error message.

## What identity looks like

| Fact | Becomes |
| --- | --- |
| API event `id` | `uid` and `message_id` as `ticketmaster:<id>`: the ladder's first rung |
| event `url` | `url`: the second rung |
| first attraction / other attractions | `HEADLINER` / `SUPPORT` |
| first embedded venue | the `VENUE` entity (a missing venue is fine) |
| `dates.start` + `dates.timezone` | local date, time and zone (venue zone as a fallback) |
| genre / sub-genre | tags |
| `priceRanges[0]` | price text |

Skipped, and counted in the run summary: cancelled, postponed, no date yet, and anything outside
the requested categories (music by default).

`evidence` is built from title, date, time and venue. It is stable for unchanged facts, so a rerun
is reported as *unchanged*, and it changes on a reschedule, which the ladder's UID rung then
applies to the existing event (the fetch time is the `sequence`, so the newer fetch wins).

## Limits, and how they are handled

- About **5 requests per second** and **5,000 per day** per key by default. Requests are spaced
  0.25 s apart; after an HTTP 429 the client waits for `Rate-Limit-Reset` (it accepts an epoch in
  seconds or milliseconds, or a number of seconds). A reset more than a minute away means the daily
  quota is spent, so it stops with a clear error instead of sleeping for hours.
- The API serves only the first **1,000** results of any one search (`size x page`). A window with
  more than that is halved until it fits; a single day that still exceeds it is fetched to the cap
  and the shortfall is printed as `truncated`.
- A query is fetched in two-week windows, so a 60-day run is about five searches plus paging.

## What is verified, and what is not

The tests use fixtures **written by hand to the documented response shape**; they were not recorded
from the live API (that needs a key). The shape comes from the public documentation, so the first
real run is the check of it. Run it with `--dry-run` and look at the skipped and rejected counts:
a surprise there means a field name differs from the documentation. A recorded fixture can then
replace the handwritten one without changing any test.

## Not covered

- **Dice** has no public API (only a partner-gated one), so it is not supported here. Dice events
  that reach you by email are handled by the normal newsletter path.
- A cancellation that arrives *after* an event was ingested is not applied: cancelled events are
  skipped, so the earlier record stays as it was.
