# Last Newsletter: product spec (ledger lane)

Status: draft 1, 2026-11-06. Builds on `PRODUCT.md` and `event-ledger.md`. Describes behavior, not visual style: no `DESIGN.md` exists yet, so layout below is structure only.

## What it is

A personal magazine made from your own newsletters. It publishes **editions**, each on its own schedule (a weekly one, a monthly one, as many as you want), and each edition publishes **issues**: numbered, dated, finite, written for one reader, with an ending. Between issues, the part of it that remembers (events, deadlines, one-time tasks) stays live as **Coming up**. You open it on a phone or desktop, read the issue, clear what is done, and it never shows you the same event twice.

**An issue**, top to bottom:
1. **Masthead**: name, issue number, date, and a one-line count ("9 stories, 4 coming up, 2 need you").
2. **Lead**: one story, chosen by rank, with a short summary and its source.
3. **Coming up**: the dated items from the ledger, ordered by date, with labeled date states and quick actions.
4. **Needs you**: one-time tasks, with the assumed-deadline label.
5. **Stories**: the rest of the news, grouped by theme, each summarized and credited to its newsletter.
6. **The end**: "That's the issue. Next one Sunday." Nothing infinite below it.

Back issues are kept and can be reopened; the ledger lives between issues.

**Honesty rule.** Magazine voice does not mean invented prose. Summaries are condensed from the email, each credited with sender and a link to the original; extracted dates carry their labels (inferred, assumed); nothing is shown that has no source email.

**Alerts are "stop press"**: the in-voice name for a notice that breaks the issue schedule (a presale opening tomorrow).

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

### 3. The issue

The magazine itself, laid out as in "What it is": masthead, lead, Coming up, Needs you, Stories, the end. Read top to bottom like a magazine, not triaged like a list. The Stories section is the stateless news lane: one story after the next, no state, nothing remembered, no action buttons. Coming up and Needs you are snapshots of the ledger and keep their quick actions. Back issues are listed by number and date.

(Screen 1, Up next, is the same ledger kept live between issues; it is Coming up plus Needs you without the editorial around it.)

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

## What counts as important

Importance comes from your knowledge store, per name. If the knowledge store says a music artist is high priority, a show with that artist headlining ranks higher: it can become the lead, sort first in its section, trigger an "important new item" alert and bring a lapsed task back once. Support acts count for less. You can also keep a watch list of senders and keywords that always count, with no knowledge store needed.

The app reads your knowledge; it does not change it. Names it sees often but does not know are listed under **Needs a look** ("artists I don't know yet") so you can decide whether to add them.

## Reliable sections

A magazine earns trust because things are where you expect them. A **section** is a standing department with a fixed name, a fixed slot and a fixed rule for what goes in it. "Concerts Coming Up" is on page 6 every issue.

A section is defined by:

| Setting | Meaning |
|---|---|
| Title | "Concerts Coming Up" |
| Slot | its position in the edition; shown as a page or section number, so slot 6 is always page 6 |
| Selector | what belongs in it: item kind (event, deadline, task), **tags** (concert, meeting, ...), senders or venues, and a date window (next 30 days) |
| Order | by date, by importance, or by mention count |
| Limit | most items shown, with "and 4 more" |
| If empty | **still printed**, with an honest line ("No concerts announced this week"), or hidden. The default is printed, because a slot that vanishes is what makes a magazine unreliable. |

Rules:
- **Each item appears once per issue**, in the first matching section by slot order. Anything that matches no section lands in the general Coming up, Needs you or Stories section, so nothing is dropped for lack of a home.
- **Page numbers are slot numbers.** They are stable only because the section list is fixed: sections that vary in length (Stories) go last. The lead and masthead are not numbered pages.
- **Tags come from three places, in order of trust:** your own correction, your rules (sender, keyword or venue maps to a tag), and the extractor's suggested category. A wrong tag is fixed in Item detail and the correction sticks.
- **A new install ships with generic sections** (Coming up, Needs you, Stories). Sections like Concerts are ones you add, usually by tagging your first few items.

## Delivery: issue cadence and stop-press alerts (configurable)

Two separate channels, both set on a fifth screen, **Settings**.

**Editions** are independent publications from the same mailbox and the same ledger. You can run several at once, each with its own cadence and contents:

| Setting | Options |
|---|---|
| Name | "The Week", "The Month", anything |
| Cadence | daily, weekly (day and time), monthly (day of month and time), every N days, or off |
| Sections | an ordered list of sections (see Reliable sections below) |
| Look-ahead | how far Coming up reaches (a weekly edition: 14 days; a monthly one: 6 weeks) |
| Sources | all newsletters, or only chosen senders or themes |
| Length | maximum number of stories |

Example: **The Week**, Sunday 6 pm, Coming up + Needs you + a short Stories section; **The Month**, the 1st at 8 am, long Stories and a six-week Coming up. Each edition numbers its own issues, and an issue covers everything since that edition's last issue, so editions never steal items from each other. The ledger is shared: mark an event done in one edition and it is done everywhere. An item may appear in more than one edition, but never twice in the same one. A new install starts with one weekly edition; you add the rest.

**Alerts (stop press)** break cadence. They are sent when something is time-critical, regardless of any edition's schedule. Each trigger is its own on/off switch with its own lead time:

| Trigger | Default | Example |
|---|---|---|
| Event reminder | on, 1 day and 2 hours before | "Show tomorrow, 8 pm" |
| Deadline approaching | on, 2 days and 1 day before | "Signup closes Friday" |
| **Sale opens** (presale or on-sale) | on, 1 day before | "Presale for the Roxy show opens tomorrow at 10 am" |
| Cancelled or postponed | on | "The Nov 7 show was cancelled" |
| Important new item | **off** until measured on real mail (Stage 4) | An artist you rank highly announces a show within 14 days |

Guardrails, all configurable:
- **One alert per item, per trigger, per lead time.** Re-ingesting the same email never re-alerts.
- **Quiet hours** (default 10 pm to 8 am): alerts wait until morning, except a sale that opens inside the quiet window, which is sent before it.
- **Daily cap** (default 5): over the cap, alerts roll into the next issue of any edition and say so.
- **Done, dismissed and snoozed items never alert.**
- **Assumed dates never alert.** A default one-week task deadline is not a real deadline, so it appears in the next issue only.
- **Late is better than silent, but only while still useful.** If the app was down when a reminder was due, it sends late if the event or sale has not happened yet; otherwise it records the miss under Needs a look.
- An alert already sent is marked in the next issue ("alerted Thursday"), so it is not a surprise or a duplicate.
- A failed send is retried from the outbox; it is never lost and never sent twice.

## Out of scope for the first release

Recurring-event expansion (store the rule, show the next one only), calendar write-back, multiple users, attachments other than calendar files, non-English mail, and a visual identity.

## Open decisions (owner)

1. How "important" is decided for resurfacing: number of mentions, per-sender weight, or the knowledge weigher.
2. Whether title + date + venue is enough to call two mentions the same event; needs a labeled sample of real repeats.
3. Reminder channel: ntfy or in-app only.
4. Whether the issue and Up next stay two screens or become one page where Coming up is the live top of the current issue.

## Build order (from the design doc)

Core first (entities, rules, ports, fakes, use cases, all tested with no dependencies), then SQLite storage, then readers and the model extractor, then reminders, then these screens.
