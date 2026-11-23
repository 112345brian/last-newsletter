"""Finding the source plugins installed next to the engine, through Python entry points.

A package adds sources by declaring, in its `pyproject.toml`:

    [project.entry-points."concert_tracker.sources"]
    my-sources = "my_package.plugins:PLUGINS"

The entry point's name is only a label (it names the failure when loading goes wrong); the object
it points at is either one `SourcePlugin` or a list/tuple of them. Discovery never raises: a plugin
that cannot be imported, is the wrong shape, or reuses a taken name becomes a `PluginFailure` that
`concert-tracker sources` and the error for an unknown source report by name, and every other
source carries on. Built-in names are reserved; among plugins the earlier entry-point name wins.
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

from dataclasses import dataclass, field
from functools import cache
from importlib.metadata import entry_points
from typing import TYPE_CHECKING

from concert_tracker_core.source_plugins import SourcePlugin, is_valid_plugin_name

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping
    from importlib.metadata import EntryPoint

ENTRY_POINT_GROUP = "concert_tracker.sources"
_LOAD_ERRORS = (
    ImportError,
    AttributeError,
    SyntaxError,
    TypeError,
    ValueError,
    OSError,
    RuntimeError,
)


@dataclass(frozen=True, slots=True)
class PluginFailure:
    """One entry point that gave no usable plugin, and why."""

    entry_point: str
    package: str
    reason: str

    def describe(self) -> str:
        return f"plugin {self.entry_point!r} (package {self.package}) was not loaded: {self.reason}"


@dataclass(frozen=True, slots=True)
class PluginRegistry:
    plugins: Mapping[str, SourcePlugin] = field(default_factory=dict)
    failures: tuple[PluginFailure, ...] = ()

    def get(self, name: str) -> SourcePlugin | None:
        return self.plugins.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.plugins))

    def failure_notes(self) -> list[str]:
        return [failure.describe() for failure in self.failures]


def _package(entry: EntryPoint) -> str:
    dist = entry.dist
    return dist.name if dist is not None else "unknown"


def _candidates_in(loaded: object) -> list[object]:
    return list(loaded) if isinstance(loaded, (list, tuple)) else [loaded]


def _problem_with(candidate: object) -> str | None:
    """Why `candidate` is not a usable plugin, or `None` when it is."""
    if not isinstance(candidate, SourcePlugin):
        return "not a SourcePlugin (needs name, description, options and build)"
    if not isinstance(candidate.name, str) or not is_valid_plugin_name(candidate.name):
        return f"plugin name {candidate.name!r} must be a lower-case slug (letters, digits, - _)"
    return None


def discover_source_plugins(
    found: Iterable[EntryPoint] | None = None, *, reserved: Collection[str] = ()
) -> PluginRegistry:
    """Load every entry point in the group. `reserved` are names the engine already owns."""
    points = sorted(
        entry_points(group=ENTRY_POINT_GROUP) if found is None else found,
        key=lambda e: (e.name, e.value),
    )
    taken = set(reserved)
    plugins: dict[str, SourcePlugin] = {}
    failures: list[PluginFailure] = []
    for entry in points:
        try:
            candidates = _candidates_in(entry.load())
        except _LOAD_ERRORS as error:
            reason = f"{error.__class__.__name__}: {error}"
            failures.append(PluginFailure(entry.name, _package(entry), reason))
            continue
        for candidate in candidates:
            problem = _problem_with(candidate)
            if problem is None and isinstance(candidate, SourcePlugin):
                if candidate.name in taken:
                    problem = f"the source name {candidate.name!r} is already taken"
                else:
                    taken.add(candidate.name)
                    plugins[candidate.name] = candidate
            if problem is not None:
                failures.append(PluginFailure(entry.name, _package(entry), problem))
    return PluginRegistry(plugins, tuple(failures))


@cache
def default_source_plugins(reserved: tuple[str, ...] = ()) -> PluginRegistry:
    """The installed plugins, discovered once per process."""
    return discover_source_plugins(reserved=reserved)


def render_plugin_listing(registry: PluginRegistry) -> str:
    """The plugins that loaded (with their options) and those that did not, one line each."""
    lines: list[str] = []
    if registry.plugins:
        lines.append("Source plugins (a `kind` for sources.json, a `fetch-events --source`):")
        for name in registry.names():
            plugin = registry.plugins[name]
            lines.append(f"  {name:<16} {plugin.description}")
            lines.extend(
                f"      option {o.name}{' (required)' if o.required else ''}: {o.help}"
                for o in plugin.options
            )
    if registry.failures:
        lines.append("Source plugins that did not load:")
        lines.extend(f"  {note}" for note in registry.failure_notes())
    return "\n".join(lines)
