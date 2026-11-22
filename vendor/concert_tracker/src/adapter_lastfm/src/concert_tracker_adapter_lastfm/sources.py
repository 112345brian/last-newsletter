"""`ArtistTagSource` and `ListeningHistory` over Last.fm, with a local tag cache."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Self

from concert_tracker_adapter_lastfm.client import LastfmClient, LastfmNotFoundError
from concert_tracker_core.taste import TasteSourceError, artist_key

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

TAG_TTL = timedelta(days=30)
NOT_FOUND_TTL = timedelta(days=7)
PERIODS = {1: "1month", 3: "3month", 6: "6month", 12: "12month"}
_PAGE = 1000
_MAX_PAGES = 5
_SCHEMA = """
CREATE TABLE IF NOT EXISTS artist_tags (
    artist_key TEXT PRIMARY KEY,
    found INTEGER NOT NULL,
    tags TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
"""


class TagCache:
    """A local SQLite cache of tag answers (`found=False` remembers "Last.fm has no such artist").

    A genre cache is regenerable and personal: it lives in the data directory and is never
    committed.
    """

    def __init__(self, path: Path | str, *, now: Callable[[], datetime]) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._now = now

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._conn.close()

    def get(self, key: str) -> tuple[bool, list[tuple[str, int]]] | None:
        """`(found, tags)` when fresh, else None."""
        row = self._conn.execute(
            "SELECT found, tags, fetched_at FROM artist_tags WHERE artist_key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        found, tags, fetched_at = row
        ttl = TAG_TTL if found else NOT_FOUND_TTL
        if self._now() - datetime.fromisoformat(fetched_at) > ttl:
            return None
        return bool(found), [(str(name), int(weight)) for name, weight in json.loads(tags)]

    def put(self, key: str, *, found: bool, tags: list[tuple[str, int]]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO artist_tags (artist_key, found, tags, fetched_at)"
            " VALUES (?, ?, ?, ?)",
            (key, int(found), json.dumps(tags), self._now().astimezone(UTC).isoformat()),
        )


class LastfmArtistTags:
    """`ArtistTagSource`: cached `artist.getTopTags`. Nothing is cached when Last.fm errored."""

    def __init__(self, client: LastfmClient, cache: TagCache) -> None:
        self._client = client
        self._cache = cache

    def tags(self, artist: str) -> list[tuple[str, int]] | None:
        key = artist_key(artist)
        if not key:
            return None
        cached = self._cache.get(key)
        if cached is not None:
            found, tags = cached
            return tags if found else None
        try:
            data = self._client.call("artist.gettoptags", artist=artist.strip(), autocorrect="1")
        except LastfmNotFoundError:
            self._cache.put(key, found=False, tags=[])
            return None
        tags = _tags_from(data)
        self._cache.put(key, found=True, tags=tags)
        return tags


def _tags_from(data: dict[str, object]) -> list[tuple[str, int]]:
    block = data.get("toptags")
    items = block.get("tag", []) if isinstance(block, dict) else []
    if isinstance(items, dict):  # a single tag comes back as an object, not a list
        items = [items]
    tags: list[tuple[str, int]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        weight = item.get("count", 0)
        tags.append(
            (
                item["name"],
                int(weight) if isinstance(weight, (int, str)) and str(weight).isdigit() else 0,
            )
        )
    return tags


class LastfmListening:
    """`ListeningHistory`: the account's top artists over a recent period."""

    def __init__(self, client: LastfmClient, user: str) -> None:
        if not user.strip():
            msg = "a Last.fm user name is required"
            raise TasteSourceError(msg)
        self._client = client
        self._user = user.strip()

    def play_counts(self, months: int) -> dict[str, int]:
        period = PERIODS.get(months)
        if period is None:
            msg = f"months must be one of {sorted(PERIODS)}"
            raise ValueError(msg)
        counts: dict[str, int] = {}
        for page in range(1, _MAX_PAGES + 1):
            try:
                data = self._client.call(
                    "user.gettopartists",
                    user=self._user,
                    period=period,
                    limit=str(_PAGE),
                    page=str(page),
                )
            except LastfmNotFoundError:
                msg = f"Last.fm has no user {self._user!r}"
                raise TasteSourceError(msg) from None
            artists, total_pages = _artists_from(data)
            counts.update(artists)
            if page >= total_pages:
                break
        return counts


def _artists_from(data: dict[str, object]) -> tuple[dict[str, int], int]:
    block = data.get("topartists")
    if not isinstance(block, dict):
        return {}, 1
    items = block.get("artist", [])
    if isinstance(items, dict):
        items = [items]
    out: dict[str, int] = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            plays = str(item.get("playcount", "0"))
            out[item["name"]] = int(plays) if plays.isdigit() else 0
    attr = block.get("@attr")
    pages = str(attr.get("totalPages", "1")) if isinstance(attr, dict) else "1"
    return out, int(pages) if pages.isdigit() else 1
