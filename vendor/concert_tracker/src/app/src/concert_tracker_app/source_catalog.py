"""Where the list of sources to run comes from: a packaged seed plus the owner's `sources.json`.

Same arrangement as the venue directory: the owner's file, `<data dir>/sources.json`, has the same
shape and wins by name, so adding, retuning or switching off a source (`"enabled": false`) never
needs a code change. A broken owner file is a `ConfigError` naming the file, never ignored.
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

import json
from importlib import resources
from typing import TYPE_CHECKING

from concert_tracker_app.errors import ConfigError
from concert_tracker_core.source_runs import SourceCatalog, SourceCatalogError, parse_source_catalog

if TYPE_CHECKING:
    from pathlib import Path

OWNER_FILE = "sources.json"
_SEED = "sources.json"


def _parse(text: str, where: str) -> SourceCatalog:
    try:
        return parse_source_catalog(json.loads(text))
    except (json.JSONDecodeError, SourceCatalogError) as error:
        msg = f"{where}: {error}"
        raise ConfigError(msg) from error


def seed_catalog() -> SourceCatalog:
    text = resources.files("concert_tracker_app").joinpath("data", _SEED).read_text("utf-8")
    return _parse(text, f"packaged {_SEED}")


def load_source_catalog(data_dir: Path) -> SourceCatalog:
    """The seed, with the owner's `<data_dir>/sources.json` laid over it when that file exists."""
    seed = seed_catalog()
    owner_path = data_dir / OWNER_FILE
    if not owner_path.is_file():
        return seed
    try:
        text = owner_path.read_text(encoding="utf-8-sig")
    except OSError as error:
        msg = f"{owner_path}: cannot be read ({error.__class__.__name__})"
        raise ConfigError(msg) from error
    return seed.with_overrides(_parse(text, str(owner_path)))
