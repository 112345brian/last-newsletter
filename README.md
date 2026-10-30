# Last Newsletter

The last newsletter-digest tool you'll need to set up: forward (or IMAP-connect)
every newsletter you subscribe to, and get back one curated daily or weekly feed —
themes ranked by how many sources covered them, not just emails in a list.

## Why another one of these

"Self-hosted" alone doesn't differentiate this from [Taran](https://github.com/jonhadfield/taran),
the closest feature match in the [prior-art survey](#prior-art) — read its source
before assuming otherwise. Taran *is* self-hostable, but "self-hosted" there means
running your own copy of a multi-tenant SaaS: Go backend, Next.js dashboard,
Postgres (Neon), Cloudflare Email Workers for inbound mail, Resend for outbound,
OAuth. That's real infrastructure to operate for one person's inbox.

The gap, confirmed by reading Taran, OpenReader, and SummerMail's own code —
not just their descriptions — is a tool with **no infrastructure beyond your own
mailbox and your own LLM key**: no managed inbox address, no OAuth, no database
server, no containers to orchestrate, no dashboard. Point it at a mailbox over
IMAP on a cron schedule, get a markdown digest out. If that stops being true —
if this grows a database or a web UI to stay competitive — the differentiator
is gone and this section needs rewriting honestly, not padded with new features.

## Prior art

> **Freshness:** checked 2026-10-30; recheck by 2027-01-30. See `freshness.json`.

Survey checked 2026-10-30. The table distinguishes direct product overlaps from
adjacent readers and workflows; “self-hosted” describes the project’s published
deployment model, while “open source” refers to a public source repository or
license. Features and availability can change; see [`freshness.json`](freshness.json)
for the recheck date and sources.

| Project | Deployment / input | What overlaps | Difference from this project’s current scope |
|---|---|---|---|
| [Taran](https://github.com/jonhadfield/taran) | Open-source, self-hosted; newsletters forwarded to its managed inbox | Daily AI newsletter summaries, key points, topics, sentiment, dashboard | Very close direct competitor; broader product with a Go backend and Next.js dashboard. Compare setup, cross-source theme synthesis, and output before claiming differentiation. |
| [AI Daily Summary](https://github.com/AlexisBalayre/ai-daily-summary) | Open-source, self-hosted; Gmail newsletters plus RSS, GitHub trending, and crawlers | Daily AI-enriched newsletter, summaries, semantic deduplication, email delivery | Broad news pipeline with dashboard, audio briefing, API/chat, and MCP server; not limited to newsletters already in a mailbox. |
| [OpenReader](https://github.com/pengyaoc/openreader) | Open-source, self-hosted; RSS/Atom and read-only IMAP newsletters | Newsletter ingestion, reading, optional AI article summaries | Reader-first, manual refresh and per-article summaries; its README explicitly says it has no scheduler. |
| [Morning Deck](https://github.com/eschnou/morningdeck) | Open-source, self-hostable; RSS, newsletters, websites, Reddit | AI ranking and scheduled personalized daily briefings | News-intelligence and content-creation platform with many source types and broader scope. |
| [SummerMail](https://github.com/wanleung/summermail) | Open-source, self-hosted; Gmail/IMAP | Importance scoring, AI email summaries, morning digest, dashboard | General inbox digest, rather than a newsletter-only product with cross-source theme ranking. |
| [LetterFeed](https://github.com/LeonMusCoden/letterfeed) | Open-source, self-hosted; email newsletters | Turns newsletter mail into RSS | Ingestion/transport bridge; the user supplies a separate feed reader and digest workflow. |
| [Omnivore](https://github.com/omnivore-app/omnivore) | Open-source, self-hosted read-it-later app; supports newsletter email | Newsletter capture and reading in a self-hosted app | Reading/library workflow rather than a scheduled cross-source digest. |
| [Readspace](https://github.com/kamui-fin/readspace) | Open-source reader with hosted and self-hosted modes; RSS and newsletter support vary by mode | Daily digest and AI summaries; self-hosted AI can use a user key | General RSS reader; its feature matrix says the hosted newsletter address is unavailable in self-hosted mode. |
| [Passel](https://www.passel.email/) | Hosted; dedicated forwarding address | AI weekly newsletter digest with cross-source themes | Strong hosted reference for the core experience; verify current details on its product pages. |
| [Meco](https://meco.app/) | Hosted reader; Gmail/Outlook connection or Meco inbox | Newsletter organization, daily digest, AI summaries and audio | Reader-first multi-device app; its docs list AI summaries/podcasts among Pro features. |
| [Readless](https://www.readless.app/) | Hosted; inbox, Substack, and RSS | Scheduled AI digest; highlights stories covered by multiple senders | Direct hosted competitor. Its current product page differentiates per-source summaries/Hot Topics from a cross-source Synthesis tier. |
| [Mailbrew](https://mailbrew.com/) | Hosted | Daily email digest of newsletters and other sources | Broader source aggregation; not self-hosted. |
| [Leave Me Alone Rollups](https://leavemealone.com/rollups/) | Hosted | Scheduled bundling of subscribed senders | Rollup/cleanup workflow, not AI synthesis. |

This scan disproves the original claim that no self-hosted/open-source option
exists. The closest code-level comparisons to evaluate next are Taran, AI Daily
Summary, and OpenReader. A meaningful differentiator must be demonstrated in the
implemented product—for example, reliable IMAP-first ingestion, transparent
cross-newsletter synthesis, simple deployment, or modular adapters—not asserted
from the scaffold alone.

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
