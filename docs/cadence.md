# Running the pipeline on a schedule

Two decoupled stages (plus read-side commands). Only stage 1 touches the network.

1. `last-newsletter fetch` -- appends new mail from IMAP to `~/.last-newsletter/raw/`.
   Incremental (resumes from `raw/.watermark` minus one day of overlap), idempotent,
   no model. Needs `LAST_NEWSLETTER_IMAP_HOST/_USER/_PASSWORD` only.
2. `last-newsletter process` -- reads **only** the raw store (no network, no credentials),
   extracts events, assigns a UUID per event, cites later mentions against the first one, and
   links ambiguous ones as possible duplicates. Prints every count (created, mentioned,
   unchanged, possible duplicates, rejected by reason, extraction failures). Re-runnable:
   processed refs are marked in `events/processed.json`; a batch with an extraction failure is
   left unmarked and retried.
   - `--extractor dated-lines` (default) is model-free. `--extractor local-llm` asks a model
     on this machine through Ollama: `LAST_NEWSLETTER_OLLAMA_MODEL` (default `gpt-oss:120b`),
     `LAST_NEWSLETTER_OLLAMA_URL` (default `http://localhost:11434`). Nothing goes to a cloud
     model and no API key is read. If Ollama is down the batch stays unprocessed, the command
     exits 1 with a message, and the next run retries it.
   - The ledger is SQLite: `events/ledger.sqlite`. An old `events/events.json` is imported once
     on the first run and renamed `events.json.imported` (kept as a backup).
   - Near-duplicates (same day, similar title, no deterministic match) are linked as *possible
     duplicates* using the local similarity index `events/similar.sqlite`. Similarity never
     merges two events by itself. The index is a cache: it is rebuilt from the ledger whenever it
     is missing or disagrees with it.
   - `--dry-run` works on a throwaway copy, saves nothing and prints only counts
     (`scripts/smoke_real_mail.sh` runs it over your real raw store).
3. `last-newsletter events [--json]` -- lists stored events: UUID, date, the mentions that cite
   it (message id, rung, evidence quote) and possible duplicates. No email bodies.
4. `last-newsletter build` -- digest from the raw store too. `build --imap` keeps the old
   direct-IMAP path.

First run (or to backfill): `last-newsletter fetch --days 7` or `--since 2026-11-01`.

## launchd (macOS), daily at 06:30

`~/Library/LaunchAgents/com.last-newsletter.fetch.plist` -- launchd does not inherit your
shell env, so put the IMAP variables in `EnvironmentVariables` (file readable only by you:
`chmod 600`), or wrap the command in a script that sources them.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.last-newsletter.fetch</string>
  <key>WorkingDirectory</key><string>/PATH/TO/last-newsletter</string>
  <key>ProgramArguments</key><array>
    <string>/opt/homebrew/bin/uv</string><string>run</string>
    <string>last-newsletter</string><string>fetch</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>LAST_NEWSLETTER_IMAP_HOST</key><string>imap.example.com</string>
    <key>LAST_NEWSLETTER_IMAP_USER</key><string>you@example.com</string>
    <key>LAST_NEWSLETTER_IMAP_PASSWORD</key><string>app-password</string>
  </dict>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>6</integer><key>Minute</key><integer>30</integer>
  </dict>
  <key>StandardOutPath</key><string>/tmp/last-newsletter-fetch.log</string>
  <key>StandardErrorPath</key><string>/tmp/last-newsletter-fetch.log</string>
</dict></plist>
```

Load: `launchctl load ~/Library/LaunchAgents/com.last-newsletter.fetch.plist`

## cron

```
30 6 * * * cd /PATH/TO/last-newsletter && . ~/.last-newsletter-env && uv run last-newsletter fetch >> ~/.last-newsletter/fetch.log 2>&1
```
where `~/.last-newsletter-env` (mode 600) exports the three IMAP variables.
