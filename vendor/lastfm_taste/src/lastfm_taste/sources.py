"""`ArtistTagSource` and `ListeningHistory` over Last.fm, with a local tag cache.

Last.fm's answers are read strictly: a body that does not have the documented shape raises
`TasteSourceError` (and is never cached) instead of being read as "no tags" or "no plays".
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

from typing import TYPE_CHECKING

from lastfm_taste.client import LastfmNotFoundError
from lastfm_taste.taste import TasteConfigurationError, TasteSourceError, artist_key

if TYPE_CHECKING:
    from lastfm_taste.client import LastfmApi
    from lastfm_taste.taste import TagStore

PERIODS = {1: "1month", 3: "3month", 6: "6month", 12: "12month"}
_PAGE = 1000
_MAX_PAGES = 5


class LastfmArtistTags:
    """`ArtistTagSource`: cached `artist.getTopTags`. Nothing is cached when Last.fm errored.

    The artist is looked up by the name given (no `autocorrect`): Last.fm answering for a
    different artist would store that artist's genres under this one's name.
    """

    def __init__(self, client: LastfmApi, cache: TagStore) -> None:
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
            data = self._client.call("artist.gettoptags", artist=artist.strip())
        except LastfmNotFoundError:
            self._cache.put(key, found=False, tags=[])
            return None
        tags = _tags_from(data)
        self._cache.put(key, found=True, tags=tags)
        return tags


def _malformed(what: str) -> TasteSourceError:
    return TasteSourceError(f"Last.fm sent {what} that is not in the documented shape")


def _as_count(value: object, what: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise _malformed(what)


def _as_text(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise _malformed(what)
    return value


def _as_object(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _malformed(what)
    return {str(k): v for k, v in value.items()}


def _rows(block: dict[str, object], key: str, what: str) -> list[dict[str, object]]:
    """The rows under `key`: a single row comes back as an object, none as a missing key."""
    items = block.get(key, [])
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise _malformed(what)
    return [_as_object(item, what) for item in items]


def _tags_from(data: dict[str, object]) -> list[tuple[str, int]]:
    block = _as_object(data.get("toptags"), "an answer without a tag list")
    return [
        (
            _as_text(row.get("name"), "a tag without a name"),
            _as_count(row.get("count"), "a tag weight"),
        )
        for row in _rows(block, "tag", "a tag list")
    ]


class LastfmListening:
    """`ListeningHistory`: the account's top artists over a recent period."""

    def __init__(self, client: LastfmApi, user: str) -> None:
        if not user.strip():
            msg = "a Last.fm user name is required"
            raise TasteConfigurationError(msg)
        self._client = client
        self._user = user.strip()

    def play_counts(self, months: int) -> dict[str, int]:
        """Plays per artist name. Raises `TasteConfigurationError` for an unsupported period and
        `TasteSourceError` when the history cannot be read in full."""
        period = PERIODS.get(months)
        if period is None:
            msg = f"months must be one of {sorted(PERIODS)}"
            raise TasteConfigurationError(msg)
        counts: dict[str, int] = {}
        total_pages = 1
        page = 1
        while page <= total_pages:
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
            if total_pages > _MAX_PAGES:
                msg = f"Last.fm history spans {total_pages} pages; only {_MAX_PAGES} are read"
                raise TasteSourceError(msg)
            for name, plays in artists:
                counts[name] = counts.get(name, 0) + plays
            page += 1
        return counts


def _artists_from(data: dict[str, object]) -> tuple[list[tuple[str, int]], int]:
    block = _as_object(data.get("topartists"), "an answer without an artist list")
    artists = [
        (
            _as_text(row.get("name"), "an artist without a name"),
            _as_count(row.get("playcount"), "a play count"),
        )
        for row in _rows(block, "artist", "an artist list")
    ]
    attr = _as_object(block.get("@attr"), "an answer without a page count")
    return artists, max(_as_count(attr.get("totalPages"), "a page count"), 1)
