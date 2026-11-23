"""Where the event type rules come from: packaged seed < region directory < `event_types.json`.

Same arrangement as the venue and promoter directories: core validates the shape
(`parse_event_type_rules`), `layered_data` reads and layers the files. A later layer's rules are
tried *before* an earlier one's, so correcting a classification (or pinning one venue to one type)
never needs a code change. A broken file is a `ConfigError` naming it, never silently ignored:
that would quietly un-classify events.
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

from typing import TYPE_CHECKING

from concert_tracker_app.layered_data import load_layered, packaged_layer
from concert_tracker_core.event_types import parse_event_type_rules

if TYPE_CHECKING:
    from pathlib import Path

    from concert_tracker_core.event_types import EventTypeRules

OWNER_FILE = "event_types.json"


def seed_event_type_rules() -> EventTypeRules:
    """The rules that ship with the program."""
    return packaged_layer(OWNER_FILE, parse_event_type_rules)


def load_event_type_rules(
    data_dir: Path | None = None, region_dir: Path | None = None
) -> EventTypeRules:
    """The seed, with the region directory's and then `<data_dir>/event_types.json` laid over it."""
    return load_layered(OWNER_FILE, parse_event_type_rules, data_dir, region_dir)
