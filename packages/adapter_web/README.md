# last-newsletter-adapter-web

A read-only, local-only Flask digest browser. Run via `last-newsletter serve`
on localhost — no deploy target, no accounts, nothing running when you're not
looking at it. Depends on `last_newsletter_core.ports.DigestRepository` only,
never on a concrete storage adapter — see the root [README](../../README.md#architecture).
