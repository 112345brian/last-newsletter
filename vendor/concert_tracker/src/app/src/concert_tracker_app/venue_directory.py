"""Where the venue directory comes from: packaged seed < region directory < `venues.json`.

Core only validates the shape (`parse_venue_directory`); reading and layering files is
`layered_data`'s job. The owner's file, `<data dir>/venues.json`, uses the same shape and wins
wherever it names the same venue, so correcting or adding a venue never needs a code change. A
broken file is a `ConfigError` naming it: never silently ignored, because that would quietly
un-classify venues.
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

from typing import TYPE_CHECKING

from concert_tracker_app.layered_data import load_layered, packaged_layer
from concert_tracker_core.venue_categories import parse_venue_directory

if TYPE_CHECKING:
    from pathlib import Path

    from concert_tracker_core.venue_categories import VenueDirectory

OWNER_FILE = "venues.json"


def seed_directory() -> VenueDirectory:
    """The venues that ship with the program."""
    return packaged_layer(OWNER_FILE, parse_venue_directory)


def load_venue_directory(data_dir: Path, region_dir: Path | None = None) -> VenueDirectory:
    """The seed, with the region directory's and then the owner's `venues.json` laid over it."""
    return load_layered(OWNER_FILE, parse_venue_directory, data_dir, region_dir)
