"""The one sanctioned way to read place-specific data: packaged < region directory < owner file.

Venues, promoters, the source catalog and the event type rules are all the same kind of thing: a
JSON file whose shape core validates, layered from three places, later layers winning:

1. the packaged file (`concert_tracker_app/data/<name>`), the program's own starting point;
2. `<region dir>/<name>`, the data of one place (a city, a scene), when a region directory is given;
3. `<data dir>/<name>`, the owner's own corrections.

A layer whose file is absent is skipped; a layer whose file is broken is a `ConfigError` naming
that file, never silently ignored (that would quietly drop venues, promoters or sources). The
region directory also holds `region.json` (`RegionProfile`: the place's name and home time zone).
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

import json
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING, Protocol, Self, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from concert_tracker_app.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

REGION_FILE = "region.json"


class Layerable(Protocol):
    def with_overrides(self, other: Self) -> Self: ...


Layered = TypeVar("Layered", bound=Layerable)


@dataclass(frozen=True, slots=True)
class RegionProfile:
    """What a region directory says about the place itself."""

    name: str
    home_tz: str


def check_region_dir(region_dir: Path | None) -> None:
    """A region directory that was named must exist."""
    if region_dir is not None and not region_dir.is_dir():
        msg = f"{region_dir}: the region directory does not exist or is not a directory"
        raise ConfigError(msg)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        msg = f"{path}: cannot be read ({error.__class__.__name__})"
        raise ConfigError(msg) from error


def _parse_layer(parse: Callable[[object], Layered], text: str, where: str) -> Layered:
    try:
        return parse(json.loads(text))
    except ValueError as error:  # json.JSONDecodeError and every shape error are ValueErrors
        msg = f"{where}: {error}"
        raise ConfigError(msg) from error


def packaged_layer(file_name: str, parse: Callable[[object], Layered]) -> Layered:
    """The file that ships with the program."""
    text = resources.files("concert_tracker_app").joinpath("data", file_name).read_text("utf-8")
    return _parse_layer(parse, text, f"packaged {file_name}")


def load_layered(
    file_name: str,
    parse: Callable[[object], Layered],
    data_dir: Path | None,
    region_dir: Path | None = None,
) -> Layered:
    """`file_name` read from the packaged data, then the region directory, then the data dir."""
    check_region_dir(region_dir)
    merged = packaged_layer(file_name, parse)
    for directory in (region_dir, data_dir):
        if directory is None or not (directory / file_name).is_file():
            continue
        path = directory / file_name
        merged = merged.with_overrides(_parse_layer(parse, _read(path), str(path)))
    return merged


def load_region_profile(region_dir: Path | None) -> RegionProfile | None:
    """`<region dir>/region.json`; `None` when no region directory is given or it has no profile."""
    if region_dir is None:
        return None
    check_region_dir(region_dir)
    path = region_dir / REGION_FILE
    if not path.is_file():
        return None
    try:
        raw = json.loads(_read(path))
    except ValueError as error:
        msg = f"{path}: {error}"
        raise ConfigError(msg) from error
    if not isinstance(raw, dict):
        msg = f"{path}: must be a JSON object with name and home_tz"
        raise ConfigError(msg)
    name, home_tz = raw.get("name"), raw.get("home_tz")
    if not isinstance(name, str) or not name.strip():
        msg = f"{path}: name must be a non-empty string"
        raise ConfigError(msg)
    if not isinstance(home_tz, str) or not _known_zone(home_tz):
        msg = f"{path}: home_tz must be an IANA time zone such as Europe/London"
        raise ConfigError(msg)
    return RegionProfile(name=name.strip(), home_tz=home_tz)


def _known_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True
