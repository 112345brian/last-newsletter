# last-newsletter-cli

Composition root: wires concrete adapters into `last_newsletter_core`'s
`BuildDigestUseCase` and exposes the `last-newsletter` command. The only package
allowed to depend on every other package — see the root [README](../../README.md#architecture).
