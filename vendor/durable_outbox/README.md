# durable_outbox

A durable local outbox for writes to a remote store: write-ahead entries with leases, crash recovery, a quarantine for corrupt files and a single guarded drainer.

Source of truth for this library. Consumers vendor it with `dfetch` pinned to a tag; do not edit the vendored copy.

    uv run pytest
