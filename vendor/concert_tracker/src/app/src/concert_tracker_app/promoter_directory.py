"""Where the promoter directory comes from: a packaged seed, plus the owner's `promoters.json`.

Same arrangement as the venue directory: core validates the shape (`parse_promoter_directory`),
this layer reads files. The owner's file, `<data dir>/promoters.json`, has the seed's shape and wins
wherever it names a promoter the seed also has. A broken owner file is a `ConfigError` naming the
file, never silently ignored: that would quietly un-recognise promoters.
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

import json
from importlib import resources
from typing import TYPE_CHECKING

from concert_tracker_app.errors import ConfigError
from concert_tracker_core.promoters import PromoterDirectory, parse_promoter_directory

if TYPE_CHECKING:
    from pathlib import Path

OWNER_FILE = "promoters.json"
_SEED = "promoters.json"


def _parse(text: str, where: str) -> PromoterDirectory:
    try:
        return parse_promoter_directory(json.loads(text))
    except ValueError as error:  # json.JSONDecodeError is a ValueError too
        msg = f"{where}: {error}"
        raise ConfigError(msg) from error


def seed_promoter_directory() -> PromoterDirectory:
    """The promoters that ship with the program."""
    text = resources.files("concert_tracker_app").joinpath("data", _SEED).read_text("utf-8")
    return _parse(text, f"packaged {_SEED}")


def load_promoter_directory(data_dir: Path | None = None) -> PromoterDirectory:
    """The seed, with `<data_dir>/promoters.json` laid over it when that file exists."""
    seed = seed_promoter_directory()
    if data_dir is None or not (data_dir / OWNER_FILE).is_file():
        return seed
    owner_path = data_dir / OWNER_FILE
    try:
        text = owner_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        msg = f"{owner_path}: cannot be read ({error.__class__.__name__})"
        raise ConfigError(msg) from error
    return seed.with_overrides(_parse(text, str(owner_path)))
