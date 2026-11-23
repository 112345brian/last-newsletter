"""The port an external package implements to add an event source (a plugin).

A plugin is one object with a `name` (what `--source` and a catalog entry's `kind` say), a
`description`, an option schema and a `build` that turns the options a user gave into an
`EventSource`, the same port the built-in scrapers implement (`EventSource.fetch(window, *, now)`
returns the events and the report). The engine discovers plugins through Python entry points (see
`concert_tracker_app.source_plugins`) and treats them exactly like built-in sources.

Signatures other packages build against:

    SourcePlugin.name: str                       # lower-case slug, e.g. "zebulon"
    SourcePlugin.description: str                # one line, shown by `concert-tracker sources`
    SourcePlugin.options: tuple[SourceOption, ...]
    SourcePlugin.build(options: Mapping[str, str], context: SourceContext) -> EventSource
    #   (may raise SourceOptionError for options it cannot use)

`options` arrives already checked against `SourcePlugin.options` by `resolve_options`: unknown
names refused, required ones present, defaults filled in. Everything is text.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from concert_tracker_core.event_ports import EventSource

_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")


class SourceOptionError(ValueError):
    """A source was given options it cannot use (unknown, missing, or invalid)."""


@dataclass(frozen=True, slots=True)
class SourceOption:
    """One option a plugin accepts: its name (`feed_url`), a one-line help and whether it is
    required. An optional option may carry a default."""

    name: str
    help: str = ""
    required: bool = False
    default: str = ""


@dataclass(frozen=True, slots=True)
class SourceContext:
    """What the engine hands a plugin that is not an option: the home time zone, the process
    environment (for keys the plugin documents), and the engine's HTTP client when it has one
    (an `httpx.Client`; `None` means build your own) and its sleep function."""

    home_tz: str
    environ: Mapping[str, str]
    http: object | None = None
    sleep: Callable[[float], None] | None = None


@runtime_checkable
class SourcePlugin(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def options(self) -> tuple[SourceOption, ...]: ...

    def build(self, options: Mapping[str, str], context: SourceContext) -> EventSource: ...


def is_valid_plugin_name(name: str) -> bool:
    """A lower-case slug: letters, digits, `-` and `_`, starting with a letter or digit."""
    return _NAME.fullmatch(name) is not None


def resolve_options(
    schema: Iterable[SourceOption], given: Mapping[str, str], *, source: str
) -> dict[str, str]:
    """`given` checked against `schema`: unknown names and missing required ones are refused,
    defaults are filled in, values are stripped. A required option given blank counts as missing."""
    declared = {option.name: option for option in schema}
    unknown = sorted(set(given) - set(declared))
    if unknown:
        known = ", ".join(sorted(declared)) or "none"
        msg = f"source {source!r}: unknown option {', '.join(unknown)} (it takes: {known})"
        raise SourceOptionError(msg)
    resolved: dict[str, str] = {}
    for name, option in declared.items():
        value = given.get(name, option.default).strip()
        if option.required and not value:
            msg = f"source {source!r}: option {name} is required"
            raise SourceOptionError(msg)
        resolved[name] = value
    return resolved
