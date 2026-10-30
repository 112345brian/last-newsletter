# Last Newsletter

The last newsletter-digest tool you'll need to set up: forward (or IMAP-connect)
every newsletter you subscribe to, and get back one curated daily or weekly feed —
themes ranked by how many sources covered them, not just emails in a list.

## Why another one of these

Several hosted products already do roughly this — see [Prior art](#prior-art) below.
What's missing is a **self-hosted, open-source** version: you point it at your own
mailbox (IMAP or Gmail) and your own LLM API key, nothing routes through a third
party's servers, and you can see exactly what prompt summarizes your email.

## Prior art

Researched before writing any code, so we're not duplicating a solved problem:

| Product | Model | Notes |
|---|---|---|
| [Passel](https://www.passel.email/) | Hosted, dedicated `@passel.email` forwarding address | Closest match: AI weekly digest, cross-source theme ranking ("4 of your newsletters covered AI agents this week"), links back to originals. Free tier + paid. |
| [Meco](https://meco.app) | Hosted, dedicated inbox address, Gmail/Outlook OAuth | iOS/Android/web reader; AI summaries are a Pro-only feature (~$3–5/mo). |
| [Readless](https://www.readless.app) | Hosted, dedicated forwarding address | AI summaries only, no free tier (Pro ~$4.90/mo, Max ~$9/mo). |
| [Mailbrew](https://mailbrew.com) | Hosted | Bundles newsletters + RSS + social feeds into one daily email; broader than just newsletters. |
| [Leave Me Alone Rollups](https://leavemealone.com/rollups/) | Hosted | Bundles sender emails into one scheduled digest; strips trackers; **no AI summarization**, just grouping. |
| Gmail filters / Unroll.me | Manual / hosted | The baseline everyone starts from; Unroll.me has a documented history of selling inbox data. |

None of the above are self-hosted or open-source. That's the gap this project fills.

## Architecture

Clean Architecture, applied as separate, independently-releasable packages so a
detail (which LLM, which mail protocol, which output format) can be swapped
without touching business rules. Dependencies only point inward:

```
packages/
  core/                    entities + use cases + ports (no I/O, no framework deps)
  adapter_email/           EmailSource  -> IMAP (implements a core port)
  adapter_summarizer/      Summarizer   -> Claude API (implements a core port)
  adapter_publish/         DigestPublisher -> Markdown file (implements a core port)
  cli/                     composition root: wires adapters into core's use case
```

- `core` depends on nothing else in this repo and must stay that way.
- Each `adapter_*` package depends only on `core`, never on another adapter.
- `cli` is the only package allowed to import everything — it's "Main as a plugin":
  swap an adapter by changing `packages/cli/src/last_newsletter_cli/main.py`, not core.

Run `uv run pytest` from the repo root to test `core`'s use cases against fake
adapters (no network, no mailbox needed).

## Status

Early scaffolding: the domain model, use case, and port interfaces are implemented
and tested. The adapters (IMAP fetch, Claude summarization, Markdown rendering) are
stubbed with `NotImplementedError` — see each adapter package's module docstring for
what's next.

## Getting started

```bash
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run ty check packages/*/src
```

## License

MIT — see [LICENSE](LICENSE).
