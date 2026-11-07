# adapter_semantic

Local similar-event index (stdlib only, no network). See `docs/design/semantic-index.md`.
A hit is only ever a *possible duplicate* candidate; callers must never auto-merge on it.
