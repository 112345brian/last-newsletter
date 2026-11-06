# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
One person, the owner, who self-hosts the app and opens it on both desktop and phone. They subscribe to many newsletters (venue and promoter mail, member mailers, Substack, hand-written group mail) and want one place that tells them what matters without reading each email.

## Product Purpose
Turns newsletters in an inbox into a digest. It separates two kinds of items:
- **News and notifications:** stateless. A story, then the next story. Nothing is remembered over time.
- **Events, deadlines and one-time tasks:** need memory. They have an identity, a date, urgency, and the user's own state (done, dismissed, snoozed). The same event mentioned in several newsletters is one item.

Success: the owner can see what is coming up and what needs action, clear it, and never see the same event twice.

## Positioning
Self-hosted and personal: it runs on the owner's machine against their own mailbox and treats events as a ledger with state, not as one more summary.

## Operating Context
- Mail arrives by IMAP; a CLI builds the digest and a small web app serves it.
- Items can be acted on: mark done or dismiss, snooze, and correct a wrong extraction (a wrong date, or a merge of duplicate events).
- A task with no stated date gets a default due date of one week after first seen. That default is shown as assumed, never as a real deadline. Important tasks may resurface once, then expire.
- Dates in newsletters are often partial (weekday and month with no year), so the interface must be able to show an inferred or uncertain date as such.

## Capabilities and Constraints
- Platform is web only; the page must work on a phone and a desktop.
- Extraction comes from an LLM and can be wrong, so every extracted item needs visible evidence (which email it came from) and a way to correct it.
- Email content is untrusted input; the interface must not render raw email HTML or follow links automatically.
- Open, not yet decided: reminder channel (ntfy or the web page), how importance is scored, and the exact identity rule for events. See `docs/research/decisions.md`.

## Brand Commitments
The product name is "Last Newsletter". No logo, voice or visual identity has been confirmed.

## Evidence on Hand
- `docs/research/gmail-survey.md`: a small first look at real mail shapes (aggregate only, no private content).
- `docs/research/scaffold-review.md`, `event-prior-art.md`, `dependency-feasibility.md`, `decisions.md`.
- No screenshots, user testing, or usage data exist. Do not fabricate any.

## Product Principles
1. News is disposable; events are remembered. The two lanes must stay visibly different.
2. Never present a guess as a fact: assumed dates, inferred years and extraction confidence are shown.
3. Every item traces back to its source email.
4. Clearing an item is fast, and a cleared item stays cleared.
5. Nothing from an email is trusted or executed.

## Accessibility & Inclusion
No product-specific requirement has been established. Phone use means touch targets and one-handed triage matter; this is an inference, not a confirmed standard.
