# ngram_index

The always-on similar-event index: character n-grams and word hashes, cosine score, vectors kept
in SQLite. Stdlib only, no network. Design: `docs/design/semantic-index.md`.

It is a library the app layer uses directly, not an adapter for a core port; the thin class that
plugs it into the core `SimilarEventIndex` port is `CoreSimilarIndex` in `concert_tracker_app`.
It sits in the `adapters` ring only because it touches the filesystem.

A hit is only ever a *possible duplicate* candidate; callers must never auto-merge on it.
