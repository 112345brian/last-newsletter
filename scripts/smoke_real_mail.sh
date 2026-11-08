#!/usr/bin/env bash
# Read-only smoke test of `process` over the mail already stored in ~/.last-newsletter/raw/
# (fill it first with `last-newsletter fetch`). Runs `process --dry-run`: it works on a
# throwaway copy of the ledger, saves nothing, and prints only counts (events found,
# possible duplicates linked, rejected by reason). It never prints a subject, sender or body.
#
#   scripts/smoke_real_mail.sh                  # local model (Ollama), as `process` would run
#   scripts/smoke_real_mail.sh --extractor dated-lines    # no model at all
#   scripts/smoke_real_mail.sh --home-tz America/Los_Angeles
set -euo pipefail

raw_dir="${HOME}/.last-newsletter/raw"
if [ ! -d "${raw_dir}" ] || [ -z "$(ls -A "${raw_dir}" 2>/dev/null)" ]; then
  echo "no raw mail in ${raw_dir}: run 'uv run last-newsletter fetch' first" >&2
  exit 2
fi

cd "$(dirname "$0")/.."
args=(process --dry-run)
has_extractor=0
for arg in "$@"; do
  if [ "${arg}" = "--extractor" ]; then has_extractor=1; fi
done
if [ "${has_extractor}" = 0 ]; then args+=(--extractor local-llm); fi
exec uv run --all-packages last-newsletter "${args[@]}" "$@"
