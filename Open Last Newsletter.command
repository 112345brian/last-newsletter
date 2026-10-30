#!/bin/bash
# Double-click this file (macOS) to open the digest browser. It opens a
# browser tab and runs in the foreground in this Terminal window -- close
# the window (or Ctrl+C) when you're done. There's nothing left running
# after that; this isn't a background service.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec uv run last-newsletter serve
