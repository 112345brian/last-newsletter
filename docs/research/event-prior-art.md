# Event ledger: prior art review

Checked: 2026-11-05. Recheck by: 2027-02-05 (tools and vendor docs move fast; LLM-security items sooner).
Method: about 20 standard-mode web searches, search-result snippets only. **No page was fetched in full**, so every claim below is only as good as the snippet behind it. Confidence tags: [H] primary source seen in results, [M] consistent secondary sources, [L] single secondary or vendor blog. Section 7 lists what I could not verify.

Scope: the persistent event/task ledger (extraction from mail, dedupe and identity, date handling, urgency and user state, security). Newsletter-digest prior art and news clustering are covered elsewhere.

## 0. Verdict first

1. **The prior art does not contain a mature open-source "newsletter to event ledger" project.** The closest things are small hobby repos (fwd2cal, Cider, Tokoro). Treat this as greenfield. What exists to borrow is parts: the iCalendar/iTIP identity model, vendor dedupe heuristics, and the security pattern.
2. **Identity: don't hash the date and title into the primary key.** The only failure report I found for title+date keys is that editing the date or title makes a new event [L]. Use a surrogate ID, keep match keys as separate mutable fields, and record every sighting as a mention row.
3. **Cheapest credible baseline:** a deterministic key ladder (ICS `UID`, then canonical URL, then normalized title + local date + venue/host), blocked on a ±1 day window, matched only against open events, with ambiguous cases left split but linked. No embeddings, no LLM matcher until measured on your own mail. Details in section 6.
4. **Security: the extractor should have no tools and no outbound reach.** It reads untrusted mail and emits a validated schema, nothing else. This is the cheapest of the defences in the literature and it fits an extraction-only design.

## 1. Tools that extract events or tasks from mail

| Name | URL | What to steal | What to avoid | License |
|---|---|---|---|---|
| Gmail / Google Calendar "events from Gmail" | https://support.google.com/calendar/answer/6084018 | Auto-created events are private to the owner, and the feature is a toggle that is off by default in the EEA [M]. Treat extraction as a suggestion the user can switch off. | Google's published reliable path is schema.org markup for reservations and ticketed events only (see section 3); do not assume it covers free newsletters. | Proprietary |
| Gmail schema.org markup | https://developers.google.com/gmail/markup/ and https://developers.google.com/gmail/actions/ | Model of "wrapper type points at an Event": `EventReservation.reservationFor` is an `Event` with `name`, `startDate`, `location` [H]. Supports JSON-LD and Microdata. | Calendar support is listed for flight, ticketed event, hotel and restaurant reservations [H]. Do not plan on bulk newsletters carrying it. | Spec is open (schema.org CC BY-SA); Gmail is proprietary |
| fwd2cal | https://github.com/moeadham/fwd2cal | Pattern we want: forward an email, LLM returns JSON, supports multi-event extraction [L]. | Writes straight to Google Calendar, so no ledger, no dedupe, no state. Needs an OpenRouter key. | not checked |
| Cider | https://github.com/ray-shen-me/cider | LLM text to `.ics` output step [L]. | Hackathon scale, hosted OpenAI API. | not checked |
| Tokoro | https://github.com/robertoranon/tokoro | A shared event layer queried by place, radius and time; closest to "ledger as a service" in concept [L]. | Built around crawling web pages and curators, not mail. | not checked |
| digikal | https://github.com/exlab-code/digikal | Has an ICS import module plus LLM analysis step, syncing to Nextcloud [L]. | Scraper-oriented, not mail. | not checked |
| OpenClaw "email-to-calendar" skills | https://aiagentsdirectory.com/skills/openclaw-openclaw-skills-1kalinafrexai-email-to-calendar | One listing advises checking the generated source quote against the email [L]. Same idea as our evidence quote. | Agent skills with no independent vetting, and an agent that can send mail while reading mail is exactly the setup in section 5. | One listing says MIT-0 per a third-party scanner [L] |
| Zapier "extract deadlines" templates | https://zapier.com/automation/use-case/using-ai-extract-and-manage-deadlines-from-emails | Confirms that the commercial pitch is "email, LLM, calendar event". | Hosted and closed; nothing about identity or updates. | Proprietary |
| Superhuman, Shortwave, Fyxer, Sunsama | n/a | **Could not establish** what any of them do for event or task extraction. Sources conflicted on Shortwave and said nothing on Sunsama. | Do not cite any of them as precedent without trying the product. | Proprietary |

Take-away: no source found documents how any of these tools keeps a recurring or updated event as one item. That is the part we are designing without a reference.

## 2. Deduplication and entity resolution

**Standard architecture.** Two stages: blocking produces candidate pairs cheaply, then a matcher decides [M]. Everything below slots into those two stages.

| Technique | Evidence | Steal | Avoid |
|---|---|---|---|
| Time+place blocking | A patent on social-network event dedupe buckets by time (1-hour slots, also checking neighbouring slots so near-midnight events are not missed) and location [L]. | Block on the date window first. It is free. | Patent is not a license to copy; the idea of bucketing is generic. |
| Vendor fuzzy defaults | Scraper actors ship title similarity ≥0.80, start within 60 min, location within 500 m; another ships Jaro-Winkler 0.82, 90 min, 800 m [L]. | Starting values to tune against our own labeled pairs. | These are defaults, not benchmarks. No precision or recall was published in what I saw. Distance does not apply to us unless a venue geocodes. |
| Canonical key then fuzzy fallback | One vendor hashes normalized title + UTC start + normalized city, then falls back to fuzzy title within a window [L]. | Exact-key fast path, fuzzy only on miss. | Note that a UTC start time is wrong for date-only events (see section 3). |
| Loosening vs tightening | A data-quality guide: strict keys miss duplicates, loose keys merge unrelated events; venue abbreviations and time-zone shifts are named sources of misses; recommends storing match evidence and a per-source reliability score [L]. | Mention table with per-source trust; keep "why merged" auditable. | Single global threshold. |
| Human review for hard cases | A discovery-platform case study routes hard cases to manual review [L]. | Our "possible duplicate" state. | Review queues nobody drains. |
| Embedding blocking | Pre-trained embeddings beat sparse tf-idf for semantic similarity (arXiv 2304.12329) [H]; LSH and kNN blocking surveys exist (2401.18064, 2504.04266). | Later upgrade for "same event, reworded". | Not needed for a first version; adds a model dependency and an index. |
| LLM pairwise matching | Pairwise judging ignores global consistency [M] (arXiv 2405.16884). In-context clustering gave fewer API calls (up to 5x) at comparable cost (arXiv 2506.02509) [M]. Blocking-aware batching cuts cost with modest quality loss (arXiv 2602.05708) [M]. | If we ever add an LLM matcher, give it the few open candidates in one prompt and ask "which one, or none". | Do not run all-pairs. Do not apply transitive closure blindly: a chain of pairwise matches can merge things that should not be merged [L]. |
| Cross-document event coreference (NLP) | Without document dates, decisions get hard (two earthquakes years apart); clustering sometimes followed event-type convention rather than time and place; temporal expressions "not very helpful" in real data (ACL 2014 Torabi Asr et al.) [M]. | Always carry the source email date into matching. | Don't expect papers on news events to transfer: they cluster mentions of one real-world occurrence, we match announcements. |
| Existing small pipeline | A project's event merger keys events by (title, start_date), uses RapidFuzz lexical blocking then embeddings, and forces a check when keys match but embeddings disagree [L]. (Search result via mintlify mirror of `strickvl/hinbox`.) | Shape of "exact key, fuzzy block, then verify". | Venue not in the key. Licence unchecked. |

Accuracy: I found **no published accuracy for event-specific dedupe** from mail or newsletters. The numbers above are vendor defaults or general ER papers on product and citation data. Any quality claim for our setting has to come from our own labeled sample.

## 3. Structured extraction of dates

### 3a. Do not call the LLM at all when the mail already says

- **iCalendar parts.** iTIP (RFC 5546) names `UID` as the primary key for a component, and `UID + RECURRENCE-ID` for one instance of a recurring event [H]. `SEQUENCE` increases per update and lower sequence numbers are ignored by attendees [M]. A single changed occurrence arrives as a VEVENT with both `UID` and `RECURRENCE-ID` and no plain-`UID` event; "naked" overrides like this are a frequent implementation bug [M]. A cancel on an instance acts like an `EXDATE` [M]. `RANGE` ("this and future") is hard to implement correctly [M]. Sources: https://datatracker.ietf.org/doc/html/rfc5546.html, https://devguide.calconnect.org/itip/introduction/.
  - Steal: use `UID` as the identity key and `SEQUENCE` as the update ordering. This is the one place a standard solves identity for us, for free.
  - Avoid: implementing `RANGE`/recurrence expansion. Store the rule, show only the next occurrence, and defer the rest.
- **Library choices (Python).** `icalendar` parses and generates RFC 5545, BSD-2-Clause per Debian/SUSE/Gentoo packaging [M] (https://icalendar.readthedocs.io/). `ics.py` is Apache-2.0 (https://icspy.readthedocs.io/) [M]. A search snippet claimed python-dateutil is GPL; **that is wrong**: it is BSD-3-Clause with Apache-2.0 for post-2017 contributions [M] (https://searchfox.org/firefox-main/source/third_party/python/python_dateutil/python_dateutil-2.9.0.post0.dist-info/METADATA).
- **schema.org JSON-LD/Microdata.** Gmail reads it, and the documented calendar path is for reservations and ticketed events (section 1) [H]. Cheap to try: parse `<script type="application/ld+json">` and check for an `Event` or `EventReservation`.
- **Open question that decides how much this matters:** what fraction of *our* mail has an `.ics` part or JSON-LD. I could not find a measured rate for newsletters. It is a one-hour measurement on the user's own mailbox before any design spend. Marking this as the first thing to do.

### 3b. LLM extraction practice for the rest

- **Relative dates are the weak point.** One study reports models doing up to 35% worse on relative references ("4 years ago") than on absolute dates, and names mis-reading the current time as an error class (arXiv 2401.12078) [M]. That study is on question answering, not extraction. Practitioner advice is to supply the email's own `Date:` header as the anchor, or have the model output the expression and resolve it in code [L].
- **Ambiguity is in the language, not just the model.** "next Friday" differs by dialect, and Duckling results depend on an explicit reference time [M] (chrono-english docs; Rasa forum thread).
- **Schema validity does not mean correct values.** Structured output guarantees shape, not truth. Practitioner guidance is: schema check, then domain rules (end ≥ start, date in a plausible window), then a verbatim-quote check against the source, then review for failures [L].
- **Steal for our schema:**
  1. Anchor `Date:` header, plus the sender's likely time zone, passed in.
  2. Model returns the *literal date text* plus a resolved ISO value. Code re-resolves the literal using a deterministic parser and compares. Disagreement lowers confidence.
  3. Distinguish three kinds of time: date-only (all-day, floating, **no UTC conversion**), local date-time with zone (IANA name, not offset), and "unspecified". The vendor key above converts to UTC, which breaks date-only events.
  4. Store `startDate` and `endDate` separately, plus `deadline` as its own kind (a deadline is not an event with duration).
  5. Required `evidence_quote`; reject any item whose quote is not a substring of the cleaned mail body.
  6. Recurrence as free text plus a flag; do not expand.
- **Avoid:** trusting the model to know today's date; storing offsets instead of zones (DST); one `datetime` field for everything.
- Date libraries (licences from memory, **not verified**): `dateparser` BSD-3, Duckling BSD-3, `human-date-parser` MIT (that one was in results).

## 4. Urgency, reminders, snooze and done state

Sources are mostly user forums, so treat as design folklore [L].

- **Two dates beat one.** OmniFocus separates a *defer* date (cannot start before) from a *due* date (overdue after). Overdue always shows regardless of defer; defer later than due silently hides a task, which users say bites them [L] (https://support.omnigroup.com/documentation/omnifocus/mac/2.3/en/dates-and-times/).
- Todoist and Things: sources disagreed; I could not confirm current behaviour.
- **Steal:**
  - States: `open`, `done`, `dismissed`, `snoozed(until)`; plus `expired` derived, not stored.
  - Snooze is a *visibility* date, never changes the event's own date. Overdue/imminent items break through a snooze (OmniFocus precedent).
  - Urgency is a pure function of (now, event date, deadline, state), recomputed at read time; do not store a score.
  - "Dismissed" must survive re-extraction: user state hangs off the surrogate ID, so a re-sent or updated mention does not resurrect it. The one deliberate exception: a *materially changed* date on a dismissed event raises a "changed" flag instead of silently reopening or silently staying closed. (My design suggestion; no source tested it.)
- **Avoid:** auto-generated reminder spam, and a "done" that is a boolean (you will want `done_at` and a reason).
- No evidence was found for any specific urgency scoring formula; treat any weights as guesses to tune by use.

## 5. Security of LLM extraction from untrusted mail

| Item | Evidence | Steal | Avoid |
|---|---|---|---|
| EchoLeak (CVE-2025-32711) | Zero-click indirect injection in Microsoft 365 Copilot; chained a classifier bypass, link redaction bypass via reference-style Markdown, auto-fetched images, a Teams proxy. Proposed mitigations: prompt partitioning, filtering, provenance-based access control, strict CSP (arXiv 2509.10540) [H]. | Do not render or auto-fetch anything from model output; our digest HTML must not load remote images chosen by extracted text. | Relying on a classifier as the defence. |
| "Invitation Is All You Need" (Gemini) | Hidden text in calendar invites triggered actions when a user asked for a summary; 14 attacks across 5 threat classes; Google says fixes deployed (arXiv 2508.12175, Black Hat 2025) [H]. | Invite and event descriptions are untrusted *as well as* mail bodies. Our `.ics` `DESCRIPTION` field is attacker text. | Assuming events from "calendar" are safer than mail. |
| Lethal trifecta (Willison) and Rule of Two (Meta) | Private data + untrusted content + external communication is the dangerous combination (Willison, 2025-06-16); Meta (2025-10-31) says hold at most two of three per session, adding "changing state" [M]. | Our extractor has untrusted input; give it **no tools, no network, no write access** beyond returning JSON. The ledger writer is deterministic code. | Giving the same agent mail read and send. Multi-agent chains can still compose into harm [L]. |
| Dual-LLM and CaMeL | Quarantined LLM without tools; CaMeL tracks data flow in a custom interpreter (arXiv 2503.18813). Willison called it the first credible mitigation not based on adding more AI. One secondary summary said 67% of attacks mitigated, conflicting with the paper's own claim [M]. | Our design is already the quarantined half. Only the schema crosses the boundary. | Treating CaMeL as a drop-in; it needs a trusted query to anchor on, which we do not have. |

Concrete rules for us, all enforceable in code:
1. Extractor output is parsed against a closed schema; free text fields are length-capped, stripped of markup, and **only ever displayed as escaped text**.
2. Never put model output into a URL, shell, SQL string or a second LLM's *instructions*. If a second LLM (matcher) is used, pass candidate text as quoted data.
3. Drop any extracted event whose `evidence_quote` is not found verbatim in the cleaned body (also defeats some hallucination).
4. Cap events per message and per sender per day; a hostile mail that fans out hundreds of events is a ledger-flooding attack and a cost attack.
5. Sender trust as a field: unknown senders can create events but are shown as unverified and never auto-snooze or auto-dismiss other events. A hostile mail must not be able to *close* someone else's event; only the user closes events. A "cancelled" claim from mail should produce a flag, not a state change, unless it is an `.ics` `METHOD:CANCEL` from the same sender that created the event.
6. Test with a small injection corpus (instructions in body, hidden CSS text, `.ics` `DESCRIPTION`, display-name tricks) and assert the output is still schema-valid and unchanged in state.

## 6. Recommended identity and dedupe approach

**Data model.** `event` (surrogate id, mutable canonical fields, user state) and `mention` (event id, message id, extracted fields, evidence quote, source trust, extracted-at). The event's current fields are derived from its mentions (latest trusted wins). Un-merge means re-pointing mentions, so a bad merge is cheap to repair.

**Match ladder, stop at first hit, always against open or recently-closed events only:**
1. `ics_uid` (+ `recurrence_id`) equals an existing event's. Apply update if `SEQUENCE` is higher; ignore if lower.
2. Canonical URL equal (registration or event page, tracking parameters and fragments stripped; resolve known redirectors only if cheap).
3. Candidate block: start date within ±1 day (all-day events by date; timed events ±24 h) **and** same sender domain or same normalized venue/host. Within the block, score normalized-title similarity (lowercase, strip punctuation, edition numbers and "reminder:", "last chance:" style prefixes, then token-set ratio). Merge only above a high threshold (start near the vendor 0.82-0.85 range and tune on labeled data). Between a low and high threshold, create a separate event with a `possible_duplicate_of` link.
4. Otherwise new event.

**Why split-by-default.** A wrong merge hides a real event (the costly error for a deadline tool); a wrong split shows two items the user can dismiss. This asymmetry is my reasoning, not a published result.

**What this assumes and how to falsify it.** Build a 100 to 200 pair labeled set from the user's own mail first; report merge precision and miss rate per ladder rung. If rung 3 misses too many reworded duplicates, add embedding similarity *inside the block only* (still no all-pairs). Add an LLM matcher last, given the ≤5 open candidates in one prompt and told to answer "id or none", per the clustering results in section 2.

## 7. Which of our assumptions the evidence contradicts

1. **"LLM extraction is how events get in."** Partly contradicted: standards (`.ics`, JSON-LD) give identity and exact dates for free where present, and `UID`/`SEQUENCE` are better identity than anything we can infer. How much of our mail has them is unmeasured. Measure it before building an extractor for everything.
2. **"Stable identity from a hash of title and date."** Contradicted by the one concrete failure report found (edits create a new event), and by `SEQUENCE`/`UID` precedent where identity is a separate, durable key.
3. **"Convert all times to UTC."** Contradicted for date-only events and DST cases (section 3b).
4. **"Embeddings or an LLM are needed for dedupe."** Not supported as a *first* step. The evidence for them is general ER on product and citation data, not events. Vendor event dedupe uses string similarity plus time and place windows.
5. **"Gmail does this already, so users may not need it."** Weakly contradicted: the documented markup path is reservations and ticketed events [H]; a Gemini "add to calendar" chip is described by a third-party guide [L]. Whether it fires on free newsletter events is unverified.
6. **"A classifier or prompt can screen hostile mail."** Contradicted by EchoLeak (classifier bypassed) and by the Gemini invite attacks. Architecture (no tools, closed schema, display escaping, state changes only by the user) is the defence that survives.
7. **"A confidence number from the model says whether to trust a date."** Unsupported. What the sources support is mechanical checks: quote-in-source, re-resolve the literal date in code, plausibility ranges.

## 8. What I could not verify

- Whether Superhuman, Shortwave, Fyxer, or Sunsama extract events or tasks, or how they dedupe them. No usable source.
- Any accuracy figure for event-specific dedupe. None found; vendor thresholds are unvalidated defaults.
- The exact required and recommended `Event` properties for Gmail/Calendar today, and whether Gmail's non-markup detection has a documented mechanism. Pages returned were older caches.
- Licenses of fwd2cal, Cider, Tokoro, digikal, and `hinbox`; licenses of dateparser, Duckling and `chrono-english` (the last two from memory). `icalendar`'s BSD-2-Clause rests on distro packaging, not the upstream file.
- That Todoist/Things lack separate start dates; current behaviour of any task app.
- CaMeL's headline result: two sources disagreed (67% mitigated vs "solves AgentDojo"). Not reconciled.
- Whether the Applied Sciences blocking-improves-LLM-matching result holds; seen as an abstract fragment only.
- The share of real newsletters carrying `.ics` or JSON-LD (section 3a). The most decision-relevant unknown.
- All paper claims are from search summaries, not full texts.

## Source list

- iTIP: https://datatracker.ietf.org/doc/html/rfc5546.html ; https://devguide.calconnect.org/itip/introduction/
- Gmail markup: https://developers.google.com/gmail/markup/ ; https://developers.google.com/gmail/actions/ ; Events from Gmail: https://support.google.com/calendar/answer/6084018
- ER: https://arxiv.org/pdf/2304.12329 ; https://arxiv.org/html/2405.16884v2 ; https://arxiv.org/pdf/2506.02509 ; https://arxiv.org/pdf/2602.05708 ; https://arxiv.org/pdf/2401.18064 ; https://arxiv.org/html/2504.04266v4
- Event dedupe practice: https://us.fitgap.com/stack-guides/managing-event-data-quality-with-deduplication-source-scoring-and-audit-trails ; https://apify.com/webdatalabs/event-scraper-pro ; https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10713320
- Event coreference: https://www.coli.uni-saarland.de/~fatemeh/ACL2014paper.pdf ; https://arxiv.org/pdf/2404.08656 ; https://arxiv.org/abs/1707.07344v1
- Temporal: https://www.emergentmind.com/papers/2603.19017 ; https://www.themoonlight.io/review/temporal-blind-spots-in-large-language-models ; https://forum.rasa.com/t/inconsistent-duckling-date-extraction-involving-relative-dates/35551 ; https://docs.rs/chrono-english/latest/src/chrono_english/lib.rs.html
- Task-date semantics: https://support.omnigroup.com/documentation/omnifocus/mac/2.3/en/dates-and-times/
- Security: https://arxiv.org/abs/2509.10540v1 ; https://arxiv.org/html/2508.12175v1 ; https://arxiv.org/pdf/2503.18813 ; https://simonwillison.net/2025/Apr/11/camel/ ; https://simonwillison.net/2025/nov/2/new-prompt-injection-papers
- Tools: https://github.com/moeadham/fwd2cal ; https://github.com/ray-shen-me/cider ; https://github.com/robertoranon/tokoro ; https://github.com/exlab-code/digikal
