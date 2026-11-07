"""Fails when any code in the workspace calls `IngestEvents.ingest(...)` and throws the
`IngestResult` away. A discarded result hides rejected candidates and lost extraction batches."""

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_METHOD = "ingest"


def discarded_calls(source: str) -> list[int]:
    """Line numbers of bare-expression statements that call `<anything>.ingest(...)`."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Expr):
            continue
        value = node.value.value if isinstance(node.value, ast.Await) else node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == _METHOD
        ):
            lines.append(node.lineno)
    return lines


def test_the_checker_itself_catches_a_discard() -> None:
    assert discarded_calls("use_case.ingest(msgs, now=now)\n") == [1]
    assert discarded_calls("await self.ingest(msgs, now=now)\n") == [1]
    assert discarded_calls("result = use_case.ingest(msgs, now=now)\n") == []
    assert discarded_calls("report(use_case.ingest(msgs, now=now))\n") == []
    assert discarded_calls("_ = use_case.ingest(msgs, now=now)\n") == []


def test_no_caller_in_the_workspace_discards_an_ingest_result() -> None:
    offenders = []
    for base in ("src", "libs"):
        for path in sorted((_ROOT / base).rglob("*.py")):
            if ".venv" in path.parts or path.name == Path(__file__).name:
                continue
            offenders += [
                f"{path.relative_to(_ROOT)}:{n}" for n in discarded_calls(path.read_text())
            ]
    assert offenders == []
