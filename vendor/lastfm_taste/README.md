# lastfm-taste


An artist's **genres** (Last.fm crowd tags, cleaned) and **your own recent play counts**, behind two
small ports, with a local cache. Personal, non-commercial use.

"Unknown is an answer, never a guess":

- An artist Last.fm does not know is `None` from `tags()` and is **absent** from the `TasteBook`;
  it is never an `ArtistTaste` with empty facts. A known artist with no tags is `[]`; one whose tags
  were all cleaned away has `genres=()`; both facts of an `ArtistTaste` are always stated.
- A lookup that could not be answered (network, rate limit, bad key, private profile, an answer not
  in the documented shape, a play history longer than the pages read) raises `TasteSourceError` and
  is never cached or recorded as "no genres".
- A request that can never work (blank key or user, an unsupported period) raises
  `TasteConfigurationError`, a `ValueError` that is *not* a `TasteSourceError`: do not retry it.
- Artists are looked up by the name given (no Last.fm `autocorrect`), so another artist's genres are
  never stored under this one's name.

## Usage

```python
from datetime import datetime
from pathlib import Path

from lastfm_taste import (
    ArtistTaste,
    LastfmArtistTags,
    LastfmClient,
    LastfmListening,
    TagCache,
    TasteBook,
    clean_genres,
)

client = LastfmClient(api_key)  # the caller supplies the key
listening = LastfmListening(client, "your-lastfm-user")
plays = listening.play_counts(months=3)  # {"Artist": plays}; 1, 3, 6 or 12 months

with TagCache(
    Path(cache_path), now=datetime.now().astimezone
) as cache:  # the caller picks the path
    tag_source = LastfmArtistTags(client, cache)
    entries = []
    for name, count in plays.items():
        tags = tag_source.tags(name)
        if tags is not None:  # unknown to Last.fm: left out of the book, not guessed
            entries.append((name, ArtistTaste(clean_genres(tags, artist=name), count)))
    book = TasteBook.from_names(entries)  # keys by artist_key; names that share one are summed

book.of(["The Headliner", "Opener"])  # ArtistTaste(genres=..., plays=<most played of them>) or None
```

Public API (`from lastfm_taste import ...`; the adapters load on first use, so importing the core
does not import `httpx` or `sqlite3`):

| Name | What it is |
| --- | --- |
| `ArtistTagSource`, `ListeningHistory` | the two ports (protocols) your code depends on |
| `TasteSourceError`, `TasteConfigurationError` | a source could not answer (the answer is *unknown*, not "no"; retry later) / the call can never work (do not retry) |
| `artist_key(name)` | how artist names are compared ("The Microblades" == "microblades!") |
| `clean_genres(tags, artist="", limit=5)` | drops weak, noise, year-like and artist-name tags |
| `ArtistTaste`, `TasteBook` | genres + plays per artist; `TasteBook.from_names` keys by `artist_key` and sums names that collide |
| `LastfmClient`, `LastfmNotFoundError`, `LastfmApi` | the HTTP client (paced, key never in errors) and the one-method protocol the sources need |
| `TagCache`, `TagStore` | SQLite cache (tags kept 30 days, "not found" 7 days) and the get/put protocol the tag source needs |
| `LastfmArtistTags`, `LastfmListening` | the ports over Last.fm |

## What is the caller's concern

The library takes everything as arguments and reads no environment variable, config file or default
path: **the API key**, **the Last.fm user name**, **where the cache lives** (`TagCache(path, now=...)`,
`:memory:` for none) and the clock. Keep the key out of the repository; store the cache in a data
directory, not in a checkout.

## Last.fm terms

- Personal, **non-commercial** use only.
- Only the **documented API** is used; do not gather Last.fm data any other way.
- When you publish anything built from it, **credit Last.fm** (with a link).
- The data (genres, play counts) is personal. **Do not commit or redistribute it**: the cache,
  play counts and any book built from them stay out of version control.

## Why not `pylast`?

[pylast](https://github.com/pylast/pylast) is a full Last.fm client (Apache-2.0, active). It offers
what this does not: the whole API (scrobbling, loving, tagging, auth/session keys, albums, tracks,
charts, libre.fm), objects for every entity, and its own request cache.

This library deliberately does not use it for transport, checked against four requirements:

1. **Offline tests against a fake transport**: no. pylast builds an `httpx.Client` to a fixed host
   inside each request, with no injectable client or transport; tests would have to monkeypatch it.
2. **Key never in errors or logs**: no. `LastFMNetwork.__repr__` includes the API key and secret.
3. **Pacing**: partly; a fixed module-level delay, not a per-client setting.
4. **Error mapping** (6 not found, 10 invalid key, 17 private, 29 rate limit): yes, via `WSError`.

So the small own client stays (`httpx`, JSON, injectable `httpx.Client`, injectable `sleep`,
`min_interval_s`). What this adds on top of any client: genre cleaning (`clean_genres`), a cache with
separate lifetimes for found and not-found, the two ports so consumers never import Last.fm, and
`artist_key` joins between tag lookups and play counts.

## Architecture

Two rings, enforced by `arborescent` (rings, forbidden effects) and `import-linter` (module layers):

- **core**: `names`, `taste` (ports, value objects, genre cleaning). No I/O, clock, env or sleeping.
- **adapters**: `client`, `tag_cache`, `sources`, and the package `__init__` (which imports core eagerly and the adapters lazily). May import core. The core ring forbids clock, env, network, database, filesystem, console and the like.

## Checks

Offline: no network, no real key.

```powershell
uv run pytest; uv run ruff check .; uv run ruff format --check .; uv run ty check src; uv run lint-imports; uv run arborescent check
```

`make check` runs the same chain where `make` is available.

Consumers vendor this library pinned to a git tag (`v*`); do not edit a vendored copy.

## Changes

- **0.2.0**: answers not in the documented shape raise `TasteSourceError` instead of reading as "no
  tags" / `0` plays; a history longer than the pages read raises instead of truncating; no
  `autocorrect`; `ArtistTaste` has no defaults; `TasteBook` validates keys, copies its mapping and
  has `from_names` (collisions are summed, not overwritten); `TasteConfigurationError`; `TagStore`
  and `LastfmApi` protocols; adapters load lazily; the core ring forbids more effects.
- **0.1.0**: extracted from concert-tracker.
