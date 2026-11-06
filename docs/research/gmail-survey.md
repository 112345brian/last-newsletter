# Gmail survey: what real newsletter mail looks like

Status: **small, partial sample.** Read-only; nothing was sent, labelled, drafted or modified.
This is public: aggregate patterns only. Examples are paraphrased; no names, addresses, links or quotes.

## Method and limits (read first)

- Reached through the Gmail connector. Tool results were captured by a local output indexer, so I could not page through the whole inbox. What I actually saw:
  - the label list (counts per label);
  - about 47 recent thread headers (roughly the first week of Nov 2026) from three listing calls;
  - ~6 full message bodies (plain text) and 1 raw MIME message (headers).
- Everything below is a **sample of ~50 threads and ~7 bodies**, not a measured inbox statistic. Per-week rates are rough.
- Not done: no 4-week sweep, no sender-by-sender header check, no HTML-only body check, no cross-issue dedupe measurement. Section 3 is mostly inference.

## 1. Which mail is a newsletter

The inbox is mostly **transactional** (account, order, ticket and security notices). True newsletters are a minority, roughly 15–20 of ~47 recent threads, in four families:

| Family | Share of newsletters in sample | Notes |
|---|---|---|
| Venue / promoter marketing (music venues, cinemas, ticket promoters, an events programme) | largest, ~8 | Calendars of shows; presale and on-sale blasts |
| Organization member mailers (membership organizations) | ~4 | Mailchimp-style; announcements, closures, sweepstakes |
| Substack | ~3 | Essays, almost no events |
| Hand-written group mail (a small group sending from a personal address, Bcc'd to members) | ~2 | Event is the whole message; **no list headers expected** (not verified) |

Rate: roughly 2–3 newsletter-ish messages per day in the sample week, i.e. perhaps 15–20/week. Low confidence.

Headers (one raw message checked, a Substack issue): has `List-Id`, `List-Unsubscribe` plus `List-Unsubscribe-Post: One-Click`, `List-Post`, `List-Archive`; **no `Precedence`**. Multipart/alternative, quoted-printable, UTF-8. Plain part ~9 KB vs HTML part ~109 KB.
- The Mailchimp-style organization mail exposes its unsubscribe only as an in-body link in the one body I read; headers not checked.
- The personal-address group mail has no list machinery as far as I can tell (Bcc to the owner, not a list).

Labels: the label list has several user labels, one of them very large and event-related. I did **not** see a "Newsletters" label in the part of the list I could read. Gmail categories (Updates / Promotions / Forums) were attached to most newsletters, but also to bank and order mail, so categories are **not** a usable selector.

Reliable selection rule, in order of confidence:
1. `List-Id` or `List-Unsubscribe` present → newsletter (catches Substack, most ESP mail).
2. Else sender on an explicit allow-list (needed for hand-written group mail and members' mailers that only put unsubscribe in the body).
3. Never use Gmail category or a user label alone. Transactional senders carry `List-Unsubscribe` too (order/ticket/bank marketing footers), so rule 1 needs a **sender deny-list or a transactional classifier** (`order`, `tickets@`, `noreply@bank`).

## 2. How dated events appear

Counts in the ~7 bodies read: events appear in 5 of 7. The two without events were a Substack essay and an organization closure notice (which *cancels* an event; see below).

Formats seen (all in body; subject carries the date only for single-event mails):
- Full weekday + month + day + year: "Friday, November 13, 2026" (venue calendar, year present).
- Weekday + abbreviated month + day, **no year**: "SATURDAY DEC 12" / "SUNDAY DEC 13" as separate lines (year must be inferred; crosses year boundaries in Dec→Jan lists).
- Label-style "MON D - Title" lines in an "upcoming" list (no year, no weekday).
- Prose "When: Sunday, November 8 11:00 am" with a separate "Where:" line giving venue and street address (hand-written group mail; weekday + date both present, which allows consistency checking).
- Numeric `M/D` and `MM/DD` dates (very common in one ticket promoter's long list, ~60 numeric date tokens in one mail).
- Times as `7pm`, `8:00pm`, `11:00 am`, often several per mail, usually door vs show vs presale.
- Date ranges / multi-night runs as adjacent lines (two nights of one show).
- Relative words ("tonight", "this week", "On Sale This Week") appear but are subordinate to absolute dates in these senders; one mail's subject said "today".
- Presale / on-sale timestamps are **not** event dates. One promoter mail was dominated by presale wording (~55 mentions). A naive "any date" extractor would create phantom events.
- Cancellation / postponement notices carry a date but state the event is cancelled with a new date TBD.
- No RSVP deadline or registration deadline seen in the bodies read.
- No recurring-event syntax ("every Tuesday") seen in the bodies read, but weekly series (a recurring group meeting, repeated cinema double-bills) recur as repeated issues.
- Venue: appears either in the sender (a venue's own list: venue is implicit in the sender) or an explicit "Where:" line; venue calendars from promoters list several venues per mail.

## 3. Duplication across and within newsletters

Directly observed: little. I did not diff issues. What the sample supports:
- **Within one issue**: the same show can appear as the featured item and again in a "more upcoming events" list, and the same show as two separate night entries.
- **Across issues**: venue calendars are rolling "on sale this week + upcoming" lists, so the same show will reappear in many consecutive issues (weekly) with unchanged wording; venue mailers also re-announce at presale, on-sale and day-of stages.
- **Across senders**: ticket promoter, venue and an order-confirmation mail can name the same show; titles likely differ (headliner vs "Artist – Tour name – Venue", added support acts, ALL CAPS, truncated).
- Observed title drift inside one mail: all-caps vs title case, a tour name as a subtitle, support acts on separate lines.

Implication (inference, not measured): exact `title+date+venue` will miss real duplicates through title drift and missing years/venues; but date + venue is a strong blocking key.

## 4. Undated action items

Present but thin in this sample:
- An organization mailer offered a prize entry ("enter today") and a "be on the lookout for a new date" promise: undated *follow-up* with no date.
- A listing-alert mail ("new listing matches your search") is an action prompt without a deadline.
- Venue/promoter mail: "on sale now", "presale info": time-boxed calls to action, usually with the sale time in text.
- No "reply by", "sign up by" or RSVP deadline found in newsletters. Deadlines mostly live in transactional mail (bank, order, security), which is outside the newsletter set.
Treat as: action items are rare in newsletters, and the dateless kind is "watch for a future date".

## 5. HTML / encoding / size / injection

- Size: raw Substack message ~177 KB (HTML ~109 KB vs ~9 KB text). Plain-text parts of venue mails were 25–45 KB, mostly tracking URLs (80–190 `http` tokens each). Strip URLs before the LLM sees the text.
- Encodings: quoted-printable, UTF-8; HTML entities appear in snippets (`&#39;`); no NUL characters or zero-width characters seen in the plain bodies I scanned.
- Tracking: nearly all links are click-tracking redirects, so link text and URLs are useless for identity; query strings can contain per-recipient IDs (do not log or commit them).
- Plain parts are usually present; where the plain part is auto-converted from HTML it is noisy (header/footer link lists, "view in browser").
- Prompt injection: a keyword scan of the 4 largest bodies for instruction-like phrases found nothing. Sample is too small to conclude; keep the extractor schema-bound and treat body text as data.

## Recommendation

### Event identity

Compute identity in two layers:
1. **Blocking key** (deterministic): `date (local, absolute) + venue_key`, where `venue_key` is the normalised venue name, or the sender domain when the sender is the venue.
2. **Match within a block**: normalised title tokens (lower-case, drop punctuation, tour/support-act words) with a fuzzy ratio threshold; fall back to an LLM same-event judgement only for ambiguous pairs in the same block.
Record every sighting (message id, issue date, stage = announce / presale / on-sale / reminder / cancelled) against the event so repeats raise confidence, not count. Cancellation or postponement updates the existing event rather than creating a new one. No embeddings needed for v1: the date+venue block is small.
If `venue` is missing, block on date + sender and mark `venue_unknown`.

### Extraction schema (per event sighting)

- `title` (as written), `title_norm`
- `start_date` (ISO, with `year_inferred: bool`), `end_date` (for multi-night), `start_time`, `doors_time`, `timezone` (assume local)
- `date_text` (original string, for audit)
- `venue_name`, `address` (if given), `venue_source` (explicit / sender)
- `kind`: show | meeting | closure | deadline | sale_window | other
- `status`: scheduled | cancelled | postponed | tbd
- `stage`: announce | presale | on_sale | reminder | cancelled (so sale times do not become events)
- `sale_start` (separate field; never `start_date`)
- `action`: none | tickets | rsvp | register | reply | sign_up; `action_deadline` (nullable)
- `source`: message id, sender, issue date, confidence 0–1
- Undated follow-ups go in a separate `task` record: `text`, `due` (nullable), `source`.

### Could not determine

- True weekly newsletter volume and the full sender list (one week, ~47 threads only).
- Whether most senders carry `List-Id` / `List-Unsubscribe` (one message's headers checked).
- Actual duplication rate across issues and senders (no diffs run).
- HTML-only newsletters, non-English mail, images-as-text flyers, attachments (.ics, PDFs).
- Rates of RSVP/registration deadlines and recurring events; none seen but sample is tiny.
- Prompt-injection prevalence.
- Whether the owner's real target set is concert/venue mail (the label list suggests yes) or general newsletters.
