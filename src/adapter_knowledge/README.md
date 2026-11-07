# last-newsletter-adapter-knowledge

Optional personalization. Implements `last_newsletter_core.ports.RelevanceWeigher`
by reading a personal `knowledge.db` (schema: https://github.com/112345brian/knowledge)
read-only — no dependency on that project's own code, only on its versioned schema.

Nothing else in this workspace depends on or imports this package. The `cli`
composition root wires `SqliteKnowledgeWeigher` into `BuildDigestUseCase` only
when a database path is configured; without that configuration, the generic
program has no idea this package exists. See the root
[README](../../README.md#architecture).
