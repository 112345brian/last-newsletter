"""Last.fm taste: an artist's genres and the owner's listening, behind two small ports.

The ports, value objects and genre cleaning (the core ring) import eagerly. The Last.fm adapters
(`httpx`, `sqlite3`) load on first use, so `import lastfm_taste` does not pull them in for a caller
that only wants the core.
"""

__arbor__ = {"ring": "adapters"}

import importlib
from typing import TYPE_CHECKING

from lastfm_taste.taste import (
    ArtistTagSource,
    ArtistTaste,
    ListeningHistory,
    TagStore,
    TasteBook,
    TasteConfigurationError,
    TasteSourceError,
    artist_key,
    clean_genres,
)

if TYPE_CHECKING:
    from lastfm_taste.client import LastfmApi, LastfmClient, LastfmNotFoundError
    from lastfm_taste.sources import LastfmArtistTags, LastfmListening
    from lastfm_taste.tag_cache import TagCache

_ADAPTERS = {
    "LastfmApi": "lastfm_taste.client",
    "LastfmClient": "lastfm_taste.client",
    "LastfmNotFoundError": "lastfm_taste.client",
    "LastfmArtistTags": "lastfm_taste.sources",
    "LastfmListening": "lastfm_taste.sources",
    "TagCache": "lastfm_taste.tag_cache",
}

__all__ = [
    "ArtistTagSource",
    "ArtistTaste",
    "LastfmApi",
    "LastfmArtistTags",
    "LastfmClient",
    "LastfmListening",
    "LastfmNotFoundError",
    "ListeningHistory",
    "TagCache",
    "TagStore",
    "TasteBook",
    "TasteConfigurationError",
    "TasteSourceError",
    "artist_key",
    "clean_genres",
]


def __getattr__(name: str) -> object:
    module = _ADAPTERS.get(name)
    if module is None:
        msg = f"module 'lastfm_taste' has no attribute {name!r}"
        raise AttributeError(msg)
    return getattr(importlib.import_module(module), name)
