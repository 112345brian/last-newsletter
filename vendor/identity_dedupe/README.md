# identity_dedupe

Collapse copies of one item by an identity ladder (id, canonical key, URL, then title evidence) without ever hiding a distinct live item.

Source of truth for this library. Consumers vendor it with `dfetch` pinned to a tag; do not edit the vendored copy.

    uv run pytest
