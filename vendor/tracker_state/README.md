# tracker_state

The tracker contract's record and action shapes (docs/tracker-contract.md, #1478 D1): generic, I/O-free types for a board that renders records into sections and runs named actions, independent of any domain.

Source of truth for this library. Consumers vendor it with `dfetch` pinned to a tag; do not edit the vendored copy.

    uv run pytest
