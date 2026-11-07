# process_lock

Cross-platform, cross-process exclusive file lock with an explicit timeout policy, and a rename that retries on Windows.

Source of truth for this library. Consumers vendor it with `dfetch` pinned to a tag; do not edit the vendored copy.

    uv run pytest
