"""Where the venue directory comes from: a packaged seed, plus the owner's own `venues.json`.

Core only validates the shape (`parse_venue_directory`); reading files is this layer's job. The
seed is a starting point for Los Angeles. The owner's file, `<data dir>/venues.json`, uses the
same shape and wins wherever it names the same venue, so correcting or adding a venue never needs
a code change. A broken owner file is a `ConfigError` naming the file: never silently ignored,
because that would quietly un-classify venues.
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

import json
from importlib import resources
from typing import TYPE_CHECKING

from concert_tracker_app.errors import ConfigError
from concert_tracker_core.venue_categories import (
    VenueDirectory,
    VenueDirectoryError,
    parse_venue_directory,
)

if TYPE_CHECKING:
    from pathlib import Path

OWNER_FILE = "venues.json"
_SEED = "venues.json"


def _parse(text: str, where: str) -> VenueDirectory:
    try:
        return parse_venue_directory(json.loads(text))
    except (json.JSONDecodeError, VenueDirectoryError) as error:
        msg = f"{where}: {error}"
        raise ConfigError(msg) from error


def seed_directory() -> VenueDirectory:
    """The venues that ship with the program."""
    text = resources.files("concert_tracker_app").joinpath("data", _SEED).read_text("utf-8")
    return _parse(text, f"packaged {_SEED}")


def load_venue_directory(data_dir: Path) -> VenueDirectory:
    """The seed, with the owner's `<data_dir>/venues.json` laid over it when that file exists."""
    seed = seed_directory()
    owner_path = data_dir / OWNER_FILE
    if not owner_path.is_file():
        return seed
    try:
        text = owner_path.read_text(encoding="utf-8-sig")
    except OSError as error:
        msg = f"{owner_path}: cannot be read ({error.__class__.__name__})"
        raise ConfigError(msg) from error
    return seed.with_overrides(_parse(text, str(owner_path)))
