"""Where the list of sources to run comes from: packaged seed < region directory < `sources.json`.

Same arrangement as the venue directory: a later layer has the same shape and wins by name, so
adding, retuning or switching off a source (`"enabled": false`) never needs a code change. A
broken file is a `ConfigError` naming it, never ignored.
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

from typing import TYPE_CHECKING

from concert_tracker_app.layered_data import load_layered, packaged_layer
from concert_tracker_core.source_runs import parse_source_catalog

if TYPE_CHECKING:
    from pathlib import Path

    from concert_tracker_core.source_runs import SourceCatalog

OWNER_FILE = "sources.json"


def seed_catalog() -> SourceCatalog:
    return packaged_layer(OWNER_FILE, parse_source_catalog)


def load_source_catalog(data_dir: Path, region_dir: Path | None = None) -> SourceCatalog:
    """The seed, with the region directory's and then the owner's `sources.json` laid over it."""
    return load_layered(OWNER_FILE, parse_source_catalog, data_dir, region_dir)
