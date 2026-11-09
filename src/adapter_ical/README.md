# last-newsletter-adapter-ical

Implements core's `EventSource` port for any published iCalendar (`.ics`) feed. A calendar URL
becomes a source by configuration, with no per-site code. It reads the feed with the
[`icalendar`](https://pypi.org/project/icalendar/) library (line folding, escapes, time zones) and
fetches it with `httpx`.

```bash
uv run last-newsletter fetch-events --source ical --home-tz America/Los_Angeles \
  --ical-url 'https://caldiscovery.com/los-angeles-ca/this-weekend-music.ics' \
  --ical-name caldiscovery --dry-run
```

- `--ical-url` is the feed. `--ical-name` is a short stable label recorded on every mention
  (default: the URL's host). `--ical-venue` fixes the venue when the whole feed is one room's
  calendar.
- **Times are shown in `--home-tz`.** Most feeds publish UTC (`...Z`); a 04:00Z start is 8pm the
  evening before in Los Angeles, and the date moves with it. Set `--home-tz` (or
  `LAST_NEWSLETTER_HOME_TZ`) or every event is shown in UTC.
- **The feed URL is treated as a secret.** Private calendars carry a token in the URL, so no
  error message or output ever contains it: failures name the status code or exception type only.
- Redirects are followed (a few hops), and the body is capped at 5 MB.

## Identity

| Fact | Becomes |
| --- | --- |
| `UID` | `uid`, core's first identity rung. If two sources re-publish one calendar, the same event is recognised with no fuzzy matching |
| `UID` + `RECURRENCE-ID` | `uid#<recurrence-id>`, one instance of a series |
| `URL` | `url`, the second rung |
| `LOCATION` | a `VENUE` only when it looks like one (see below), else none |
| `DTSTART`/`DTEND` | local date, time and end time (an end more than a day after the start is dropped) |
| `CATEGORIES` | tags |
| `SEQUENCE` | the update order if the feed has it, otherwise the fetch time |

**Venue from `LOCATION` is a guess.** "The Mayan, 1038 S Hill St, Los Angeles" gives "The Mayan";
"Globe Theatre" gives "Globe Theatre"; "Pomona, CA", "Los Angeles, CA 90015" and a bare street
address give none; a `Location X [/link]` label some feeds add is removed. A wrong or missing venue
only weakens matching against other sources, it never merges anything. Use `--ical-venue` when you
know better.

## What is skipped, and counted

Every skip is a counted reason in the run summary, never silent:

- `recurring`: an event with an `RRULE` is not expanded into its occurrences (none of the feeds
  checked so far use them; `recurring-ical-events` is the library to add if one does).
- `multi_day`: an all-day span longer than a day (a three-month "Second Saturdays" series is not
  one show, and core models one event per date).
- `cancelled`, and events with no `UID`, title or start.

## What is verified

Tested on synthetic calendars covering UTC, `TZID` and floating times, all-day events, folded and
escaped text, instances of a series, and every skip reason. It was also run once against the real
CalDiscovery weekend feed (135 events in, 131 candidates out, 3 multi-day spans skipped, 109 venues
guessed across 65 distinct rooms). Whether a given aggregator's terms allow your use is not
checked here: read each feed's terms before relying on it, especially for anything you republish.
