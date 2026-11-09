# last-newsletter-adapter-squarespace

Implements core's `EventSource` port for any Squarespace site with an events page. Squarespace
publishes a page's content as JSON when `?format=json` is added to its address, and many small
venues and promoters run their listings this way (The Smell, Living Earth and Healing Force of the
Universe among them). One adapter covers them all; each is a configuration, not code.

```bash
# a room's own calendar
uv run last-newsletter fetch-events --source squarespace --home-tz America/Los_Angeles \
  --feed-url https://www.thesmell.org/events --feed-name thesmell --feed-venue "The Smell" --dry-run

# a promoter whose shows are at various places
uv run last-newsletter fetch-events --source squarespace --home-tz America/Los_Angeles \
  --feed-url https://www.livingearth.la/gatherings --feed-name livingearth \
  --feed-organizer "Living Earth" --dry-run
```

A feed must say whether it is **one room's calendar** (`--feed-venue`) or **a promoter's**
(`--feed-organizer`), not both and not neither. A promoter's shows are at various places, so
giving the promoter a venue would be inventing a fact: it is recorded as the `ORGANIZER` and the
event carries no venue. (The map location in the data is not used: it is a placeholder, a spot in
New York, on at least one real site.)

## What it reads

| Fact | Becomes |
| --- | --- |
| item `id` | `uid` and `message_id` as `<name>:<id>` |
| `startDate` (epoch ms) | the start, shown in `--home-tz`. It is a real instant, checked against the times written in the listings themselves |
| `title` | the title, with HTML entities decoded |
| `tags`, `excerpt` | the lineup, price, promoter and ticket link (below) |
| a link in the excerpt, else the page address | `url` |
| `updatedOn` | the update order, so an edited listing wins over the stored one |

`endDate` is **not used**. Sites leave it at the editor's default length (every Smell show ends
exactly two hours after it starts), so it says nothing about when a show ends.

## Date-titled listings

Many DIY venues title every listing with its date ("Thursday, November 12, 2026") and put the
bill in the body. When a title is only a date, the title is rebuilt as the lineup, taken from the
item's tags (the bands plus one date tag), or from the excerpt's lines if the tags hold only the
date. A line ending "presents…" names the promoter, who is recorded as an `ORGANIZER` and removed
from the lineup. A price line (`$10 in advance…`) becomes the price. The lineup is in the title,
not as per-band entities: a poster's order is not a billing order.

## Behaviour worth knowing

- The page lists **all upcoming events**; the past ones are ignored. A page with no `upcoming`
  list is refused as "not a Squarespace events page".
- Every skip is a counted reason in the run summary: `no_id`, `no_title`, `no_date`.
- A redirect (to the canonical host) is followed a few hops; the body is capped at 10 MB, since
  these pages carry the whole site's settings (one real page is 1.4 MB).

## What is verified

Synthetic items in the shape observed on 2026-11-09 (field names, the epoch times, the date-only
titles, the tag and excerpt layout) cover every rule above. It was also run once against the real
pages through the CLI as a dry run: The Smell gave 9 events with correct lineups, 8:00 and 9:00 pm
times, prices, promoters and ticket links; Living Earth gave 6; Healing Force gave 0, because its
upcoming list was genuinely empty.

Whether a venue's terms allow your use is not checked here. These are public pages that a browser
loads, read at the rate of one request per run, but read each site's terms before relying on it,
especially for anything you republish.
