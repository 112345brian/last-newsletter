# Last Newsletter: product spec (ledger lane)

Status: draft 1, 2026-11-06. Builds on `PRODUCT.md` and `event-ledger.md`. Describes behavior, not visual style: no `DESIGN.md` exists yet, so layout below is structure only.

## What it is

One person's inbox of newsletters, turned into two things: a **digest** of news you can skim and forget, and a **ledger** of events, deadlines and one-time tasks that it remembers for you. You open it on a phone or desktop, clear what is done, and it never shows you the same event twice.

## Screens

Five screens (the fifth, Settings, is described under Delivery), one navigation bar. Web only, phone first.

### 1. Up next (home)

The ledger, ordered by urgency band, then by importance. Each row is one item.

```
UP NEXT                                   3 need action
--------------------------------------------------------
TOMORROW
  Sat Nov 7 · 8:00 pm
  Show at the Roxy                       2 emails
  [Done] [Snooze] [Dismiss]

THIS WEEK
  Fri Nov 13
  Member meeting                         1 email
  [Done] [Snooze] [Dismiss]

  Due Nov 13 · assumed
  Renew the reading-group signup         1 email
  [Done] [Snooze] [Dismiss]

LATER
  Sat Dec 12 · year inferred
  Holiday show                           3 emails
```

Row rules:
- Date states are always labeled: a stated date has no label; **year inferred**, **time unclear**, or **assumed** (the default one-week task deadline) are shown beside it. A guess is never styled like a fact.
- "N emails" is the number of mentions. Repeats raise that number; they never add rows.
- Possible duplicates are shown as a small "maybe the same as" link, not merged.
- Snoozed, done and dismissed items leave this screen. Empty state: "Nothing coming up", with the date of the last successful check.

### 2. Item detail

Opened from a row. Shows what the app believes and where it came from.
- Title, date and time (with state labels), venue, kind (event, deadline, task).
- **Evidence**: the quoted line from the email, and the sender and date of every email that mentioned it, oldest first. Links open the stored message text, never raw HTML.
- Actions: Done, Dismiss, Snooze (tonight, tomorrow, this weekend, pick a date), **Correct** (edit date or title, mark "not an event"), **Merge with...** and **Split**.
- A correction is kept as an override: later emails update mentions but never undo what you set.

### 3. Digest

The stateless news lane: today's stories in order, one after the next. Nothing here has state or a count, and nothing is remembered between days. Visibly different from Up next (no action buttons, no dates-as-urgency).

### 4. Needs a look

The things the app could not decide, so nothing fails silently.
- Extractions that failed or were refused (cost, privacy filter), with the reason and a Retry.
- Candidates rejected as suspect (date in the past, no evidence in the email).
- Possible duplicates awaiting a merge or "keep separate".
- Source health: a sender or source that returned nothing for several runs, or failed to fetch.
- Done and dismissed history, with Undo.

## Behavior in plain words

- **New mail arrives** (IMAP, on a schedule). Machine-readable events in the email (calendar attachments, structured data) are read first, at no model cost. The model reads what is left. Every candidate is checked before it becomes an item.
- **Same event, many emails**: one item, with a growing list of mentions.
- **Cancellation or postponement notice**: dismisses the matching item with the reason "cancelled by source", and keeps the email as evidence.
- **Task with no date**: due one week after first seen, shown as **assumed**. An important task may come back once after it lapses, then expires. Done and dismissed always win.
- **Presale and on-sale times** are not event dates. They are stored as sale information on the item.
- **Reminders and alerts**: see Delivery below. Sent through a durable outbox so a crash neither loses nor repeats one. Channel (ntfy or in-app only) is undecided.
- **Untrusted input**: no email HTML is rendered, no link is followed or fetched, and the model gets no tools.

## Delivery: digest cadence and alerts (configurable)

Two separate channels, both set on a fifth screen, **Settings**.

**Digest** is scheduled: daily, weekly, or off, with a day and time. A weekly wrap-up is just `weekly, Sunday 6 pm`. It lists everything open, so nothing depends on an alert having been seen.

**Alerts** break cadence. They are sent when something is time-critical, regardless of the digest schedule. Each trigger is its own on/off switch with its own lead time:

| Trigger | Default | Example |
|---|---|---|
| Event reminder | on, 1 day and 2 hours before | "Show tomorrow, 8 pm" |
| Deadline approaching | on, 2 days and 1 day before | "Signup closes Friday" |
| **Sale opens** (presale or on-sale) | on, 1 day before | "Presale for the Roxy show opens tomorrow at 10 am" |
| Cancelled or postponed | on | "The Nov 7 show was cancelled" |
| Important new item | **off** until importance is decided | A watch-listed sender announces something dated within 14 days |

Guardrails, all configurable:
- **One alert per item, per trigger, per lead time.** Re-ingesting the same email never re-alerts.
- **Quiet hours** (default 10 pm to 8 am): alerts wait until morning, except a sale that opens inside the quiet window, which is sent before it.
- **Daily cap** (default 5): over the cap, alerts roll into the next digest and say so.
- **Done, dismissed and snoozed items never alert.**
- **Assumed dates never alert.** A default one-week task deadline is not a real deadline, so it appears in the digest only.
- **Late is better than silent, but only while still useful.** If the app was down when a reminder was due, it sends late if the event or sale has not happened yet; otherwise it records the miss under Needs a look.
- An alert already sent is marked in the next digest ("alerted Thursday"), so it is not a surprise or a duplicate.
- A failed send is retried from the outbox; it is never lost and never sent twice.

## Out of scope for the first release

Recurring-event expansion (store the rule, show the next one only), calendar write-back, multiple users, attachments other than calendar files, non-English mail, and a visual identity.

## Open decisions (owner)

1. How "important" is decided for resurfacing: number of mentions, per-sender weight, or the knowledge weigher.
2. Whether title + date + venue is enough to call two mentions the same event; needs a labeled sample of real repeats.
3. Reminder channel: ntfy or in-app only.
4. Whether the Digest and Up next share one page with two tabs or are separate screens.

## Build order (from the design doc)

Core first (entities, rules, ports, fakes, use cases, all tested with no dependencies), then SQLite storage, then readers and the model extractor, then reminders, then these screens.
