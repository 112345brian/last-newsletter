"""The three hand-maintained package lists in the root pyproject must agree with the disk.

A package missing from `root_packages` is not analysed by import-linter at all, so a new
package could break the dependency rule without anything failing. A `members` entry that does
not exist is silent too. These tests make both loud.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
# Where packages live. concert-tracker is vendored whole, so its packages sit one level deeper.
_PACKAGE_PARENTS = ("src", "libs", "vendor", "vendor/concert_tracker/src")


def _pyproject() -> dict[str, Any]:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text())


def _member_dirs() -> set[str]:
    return {
        f"{root}/{path.name}"
        for root in _PACKAGE_PARENTS
        for path in (_ROOT / root).iterdir()
        if (path / "pyproject.toml").is_file()
    }


def _import_names_on_disk() -> set[str]:
    return {
        init.parent.name
        for root in _PACKAGE_PARENTS
        for init in (_ROOT / root).glob("*/src/*/__init__.py")
    }


def _layer_names(pyproject: dict[str, Any]) -> list[str]:
    contracts = pyproject["tool"]["importlinter"]["contracts"]
    layered = [c for c in contracts if c["type"] == "layers"]
    assert len(layered) == 1, "expected exactly one layers contract"
    return [name.strip() for row in layered[0]["layers"] for name in row.split("|")]


def test_every_workspace_member_exists() -> None:
    members = set(_pyproject()["tool"]["uv"]["workspace"]["members"])

    missing = {m for m in members if not (_ROOT / m / "pyproject.toml").is_file()}

    assert not missing, f"workspace members with no package on disk: {sorted(missing)}"


def test_every_package_on_disk_is_a_workspace_member() -> None:
    members = set(_pyproject()["tool"]["uv"]["workspace"]["members"])

    unregistered = _member_dirs() - members

    assert not unregistered, f"packages not in workspace members: {sorted(unregistered)}"


def test_root_packages_match_the_import_packages_on_disk() -> None:
    root_packages = set(_pyproject()["tool"]["importlinter"]["root_packages"])
    on_disk = _import_names_on_disk()

    assert root_packages == on_disk, (
        f"not analysed by import-linter: {sorted(on_disk - root_packages)}; "
        f"listed but absent: {sorted(root_packages - on_disk)}"
    )


def test_every_root_package_is_placed_in_exactly_one_layer() -> None:
    pyproject = _pyproject()
    root_packages = set(pyproject["tool"]["importlinter"]["root_packages"])
    layered = _layer_names(pyproject)

    duplicated = sorted({name for name in layered if layered.count(name) > 1})
    unplaced = sorted(root_packages - set(layered))
    unknown = sorted(set(layered) - root_packages)

    assert not duplicated, f"in more than one layer: {duplicated}"
    assert not unplaced, f"analysed but in no layer: {unplaced}"
    assert not unknown, f"layered but not a root package: {unknown}"
