"""Where the promoter directory comes from: packaged seed < region directory < `promoters.json`.

Same arrangement as the venue directory: core validates the shape (`parse_promoter_directory`),
`layered_data` reads and layers the files. A later layer wins wherever it names a promoter an
earlier one has. A broken file is a `ConfigError` naming it, never silently ignored: that would
quietly un-recognise promoters.
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

from typing import TYPE_CHECKING

from concert_tracker_app.layered_data import load_layered, packaged_layer
from concert_tracker_core.promoters import parse_promoter_directory

if TYPE_CHECKING:
    from pathlib import Path

    from concert_tracker_core.promoters import PromoterDirectory

OWNER_FILE = "promoters.json"


def seed_promoter_directory() -> PromoterDirectory:
    """The promoters that ship with the program."""
    return packaged_layer(OWNER_FILE, parse_promoter_directory)


def load_promoter_directory(
    data_dir: Path | None = None, region_dir: Path | None = None
) -> PromoterDirectory:
    """The seed, with the region directory's and then `<data_dir>/promoters.json` laid over it."""
    return load_layered(OWNER_FILE, parse_promoter_directory, data_dir, region_dir)
