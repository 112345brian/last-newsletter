"""The export as text, and the JSON Schema that describes it.

`render_export_json` is deterministic: keys in the schema's order, two-space indent, UTF-8 without
escapes, one trailing newline, so exporting an unchanged ledger twice gives identical bytes and a
diff of two exports shows only real changes.
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

import json
from importlib import resources
from typing import TYPE_CHECKING

from concert_tracker_core.published_events import export_as_data

if TYPE_CHECKING:
    from concert_tracker_core.published_events import EventExport

SCHEMA_FILE = "export.schema.json"


def render_export_json(export: EventExport) -> str:
    return json.dumps(export_as_data(export), indent=2, ensure_ascii=False) + "\n"


def export_schema() -> dict[str, object]:
    """The JSON Schema (draft 2020-12) of `render_export_json`'s output."""
    text = resources.files("concert_tracker_app").joinpath("data", SCHEMA_FILE).read_text("utf-8")
    return dict(json.loads(text))
