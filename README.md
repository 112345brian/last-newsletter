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
  adapter_email/           EmailSource      -> IMAP (implements a core port)
  adapter_summarizer/      Summarizer       -> Claude API (implements a core port)
  adapter_publish/         DigestPublisher  -> Markdown file (implements a core port)
  adapter_storage/         DigestRepository -> flat JSON files (implements a core port)
  adapter_web/             read-only Flask digest browser, consumes DigestRepository
  adapter_knowledge/       RelevanceWeigher -> a personal knowledge.db (optional, opt-in)
  cli/                     composition root: wires adapters into core's use case
  text_match/              standalone, zero-dependency: whole-word term matching
  mailtext/                standalone: MIME header decoding + body text extraction
```

- `core` depends on nothing else in this repo and must stay that way.
- Each `adapter_*` package depends only on `core`, never on another adapter —
  `adapter_web` depends on the `DigestRepository` port, not on `adapter_storage`.
- `cli` is the only package allowed to import everything — it's "Main as a plugin":
  swap an adapter by changing `packages/cli/src/last_newsletter_cli/main.py`, not core.
- `text_match` and `mailtext` are not about newsletters at all — they're generic
  utilities (term matching; email MIME parsing) that happen to live in this
  workspace because that's where they were first needed, written and named as if
  a stranger might `pip install` just one of them. Neither depends on `core` or
  any adapter; `core` must never depend on either. `text_match` is a straight port
  of [`knowledge`](https://github.com/112345brian/knowledge)'s own `textmatch.py`
  — extracted into its own package once this repo became a second real consumer
  of the identical logic, rather than copy-pasted a second time.
- This isn't just asserted — `uv run lint-imports` (import-linter) statically checks
  every import in the repo against the layered contract in `pyproject.toml`
  (`[tool.importlinter]`) and fails the build if an adapter imports another adapter,
  or core imports anything. (`tach` was tried first, since it's used for the same
  purpose elsewhere; its module-boundary checker doesn't correctly resolve imports
  across a `uv` workspace's multiple per-package `src/` roots in the version
  available at the time — verified by hand, not assumed — so import-linter, which
  analyzes the real installed import graph instead of crawling source directories,
  is what's actually wired in.)

**Ranking isn't just "most mentions this week."** A theme can matter for reasons
a single period's mention count misses entirely:

- **A known future date** (a conference, a deadline) — the Summarizer sets
  `Theme.relevant_until` when it can extract one, and the digest keeps surfacing
  it, ranked by proximity to that date, until it passes.
- **Recurrence across periods** (an ongoing saga) — `BuildDigestUseCase` looks
  back one digest (via `DigestRepository`), offers still-live prior themes back
  to the Summarizer, and a theme the Summarizer recognizes as continuing gets
  its `streak` bumped, which outranks an equally-covered one-off.
- **Personal relevance** — any number of `RelevanceWeigher`s (zero by default;
  `adapter_knowledge` is one optional implementation, reading a personal
  `knowledge.db` read-only) translate their own signal into a float added to a
  theme's ranking weight. Core never knows what produced that number.

`last-newsletter build` fetches, summarizes, weighs, ranks, and writes a digest.
`last-newsletter serve` (or double-click `Open Last Newsletter.command`) opens a
read-only local browser over past digests. Both are deliberately foreground-only
— no background daemon, no process supervision — because "click an icon, look
at it, close it" doesn't need a service kept alive in between.

## Verifying this repo

```bash
uv run --package last-newsletter-cli python -c "import last_newsletter_cli"  # builds the full graph into .venv
uv run --package last-newsletter-cli pytest   # every package's tests (fakes only — no network, no mailbox)
uv run ruff check .                           # lint
uv run ruff format --check .                  # formatting
uv run ty check packages/*/src                # strict type-checking (see pyproject.toml's [tool.ty.rules])
uv run lint-imports                            # Clean Architecture boundaries (see pyproject.toml's [tool.importlinter])
```

The first command matters: `uv sync` alone only installs the root project's own
dependency groups, not every workspace member — building the `cli` package
pulls in (and installs) the whole dependency graph, which `ty`, `pytest`, and
anything that imports across packages need already present in `.venv`.

## Status

The domain model, use case (including continuity/ranking), every port, IMAP
fetch (`adapter_email`, via `imapclient`), Markdown rendering
(`adapter_publish`), and the Claude call itself (`adapter_summarizer`, forcing
a structured tool response rather than parsing prose) are implemented and
tested — 73 tests passing, strict `ty`, clean `ruff`, and `import-linter`'s
architecture contract all green. `adapter_knowledge`'s SQL query is grounded
in the real, versioned `knowledge.db` schema but not yet exercised against a
real database — see its module docstring.

## License

MIT — see [LICENSE](LICENSE).
