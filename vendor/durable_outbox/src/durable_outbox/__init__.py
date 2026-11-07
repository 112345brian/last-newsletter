"""A durable local outbox for writes to a remote store: write-ahead entries with leases, crash recovery, a quarantine for corrupt files and a single guarded drainer."""

__arbor__ = {"ring": "adapters"}
