# usage_ledger_port

The usage-ledger port: a Protocol for reading ledger rows and recording a skipped-for-budget row, plus a bind slot that fails loudly when unbound.

Source of truth for this library. Consumers vendor it with `dfetch` pinned to a tag; do not edit the vendored copy.

    uv run pytest
