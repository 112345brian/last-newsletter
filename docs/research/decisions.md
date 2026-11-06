# Ledger design decisions

Recorded 2026-11-06 from the owner's answers in session. Status: decided unless marked open.

## Scope
- The ledger holds dated events, dated deadlines, and one-time tasks.
- News and notifications stay stateless in the digest, as today.

## Tasks (undated action items)
- A task is a one-time item with no stated date, for example "reply to confirm" or "update your details".
- Default due date is first seen plus 7 days, so tasks use the same urgency path as dated items.
- The default date is flagged as assumed (`due_is_default`), so reminders never show it as a real deadline.
- A repeat sighting of the same task records another mention and does not reset the week.
- Resurfacing: depending on importance, a task can come back after it lapses. Cap: once, then it expires.
- Done and dismissed always win over resurfacing.

## Open
- Source of "importance": source count, per-sender weight, or the knowledge weigher (weak on whole titles).
- Event identity rule: needs a measured dedupe sample from real mail.
- Where key normalization lives, because `core` cannot import `text_match`.
- Reminder channel: ntfy or the web page.
