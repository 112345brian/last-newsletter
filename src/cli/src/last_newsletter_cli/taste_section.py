"""`build`'s taste options: Last.fm genres and listening applied to the "Coming up" section.

Nothing here touches the network unless a taste option was given. Someone who asked for a genre
filter or a ranking must not silently get the plain list, so a missing key or user name, or a
refusal from Last.fm, is a `ConfigError`. A single artist that could not be looked up only leaves
that artist's genres unknown, and the warning says how many.

Genres need `$CONCERT_TRACKER_LASTFM_KEY`; play counts also need `$CONCERT_TRACKER_LASTFM_USER`.
The tag cache lives under the data directory and is never part of the repository.
"""

from __future__ import annotations

__arbor__ = {"ring": "cli"}

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from concert_tracker_app import ConfigError
from concert_tracker_app.taste_view import with_taste
from concert_tracker_core.taste import TasteFilter
from lastfm_taste import (
    LastfmArtistTags,
    LastfmClient,
    LastfmListening,
    TagCache,
    TasteConfigurationError,
    TasteSourceError,
)

from last_newsletter_cli.upcoming_section import UpcomingOutcome, describe_included

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import datetime

KEY_VARIABLE = "CONCERT_TRACKER_LASTFM_KEY"
USER_VARIABLE = "CONCERT_TRACKER_LASTFM_USER"
CACHE_PATH = Path("taste") / "lastfm_cache.sqlite"
LISTENED_MONTHS = (1, 3, 6, 12)
DEFAULT_LISTENED_MONTHS = 3


@dataclass(frozen=True, slots=True)
class TasteOptions:
    genres: tuple[str, ...] = ()
    min_plays: int = 0
    rank: bool = False
    show: bool = False
    months: int = DEFAULT_LISTENED_MONTHS

    @property
    def wanted(self) -> bool:
        return bool(self.genres or self.min_plays or self.rank or self.show)

    @property
    def needs_genres(self) -> bool:
        return bool(self.genres or self.show)

    @property
    def needs_listening(self) -> bool:
        return bool(self.min_plays or self.rank)


NO_TASTE = TasteOptions()


@dataclass(frozen=True, slots=True)
class TasteOutcome:
    section: UpcomingOutcome
    warning: str | None = None


def apply_taste_section(
    outcome: UpcomingOutcome,
    options: TasteOptions,
    data_dir: Path,
    environ: Mapping[str, str],
    now: Callable[[], datetime],
) -> TasteOutcome:
    """`outcome` with genres and plays added and narrowed per `options`.

    The section line is rewritten so it says how many events a genre filter left out for lack of
    genres. Raises `ConfigError` when Last.fm cannot be used.
    """
    if not options.wanted or outcome.upcoming is None:
        return TasteOutcome(outcome)
    key = environ.get(KEY_VARIABLE, "").strip()
    if not key:
        msg = f"--genre, --listened, --rank and --taste need a Last.fm API key in ${KEY_VARIABLE}"
        raise ConfigError(msg)
    user = environ.get(USER_VARIABLE, "").strip()
    if options.needs_listening and not user:
        msg = f"--listened and --rank need your Last.fm user name in ${USER_VARIABLE}"
        raise ConfigError(msg)
    wanted = TasteFilter.of(options.genres, min_plays=options.min_plays, rank=options.rank)
    try:
        client = LastfmClient(key)
        listens = options.needs_listening or options.show
        history = LastfmListening(client, user) if user and listens else None
        cache_path = data_dir / CACHE_PATH
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with TagCache(cache_path, now=now) as cache:
            tags = LastfmArtistTags(client, cache) if options.needs_genres else None
            narrowed, report = with_taste(outcome.upcoming, tags, history, wanted, options.months)
    except (TasteSourceError, TasteConfigurationError) as error:
        raise ConfigError(str(error)) from None
    warning = (
        f"warning: {report.lookup_failures} artist lookup(s) on Last.fm failed; "
        "those artists' genres are unknown"
        if report.lookup_failures
        else None
    )
    section = UpcomingOutcome(
        narrowed if narrowed.event_count else None, describe_included(narrowed), outcome.warning
    )
    return TasteOutcome(section, warning)
