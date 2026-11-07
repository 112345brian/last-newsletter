"""The lib imports the standard library only: no application package, no sibling lib."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src" / "text_normalize"
_APP_PACKAGES = frozenset({
    "jobsearch", "jobsearch_cli", "state", "records", "client", "digest", "tracker", "commands",
    "job_repository", "job_activity_repository", "composition", "app_logging", "runtime_seams",
    "cover_letter", "resume", "llmhost", "evalkit", "tracker_state", "urgency", "identity_dedupe",
    "source_dates",
})


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_module_imports_an_app_package() -> None:
    offenders = {
        path.name: sorted(_imported_roots(path) & _APP_PACKAGES)
        for path in _SRC.glob("*.py")
        if _imported_roots(path) & _APP_PACKAGES
    }
    assert not offenders, f"app imports in the lib: {offenders}"


def test_every_import_is_stdlib_or_this_lib() -> None:
    allowed = set(sys.stdlib_module_names) | {"text_normalize", "__future__"}
    for path in _SRC.glob("*.py"):
        assert _imported_roots(path) <= allowed, (path.name, sorted(_imported_roots(path) - allowed))
