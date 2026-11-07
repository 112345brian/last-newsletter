"""Enforces, in `make check`, that `llmhost.Provider` is the ONLY way code reaches a model.

(a) nothing outside libs/llmhost imports a model SDK or names a known model endpoint;
(c) every caller of `Provider.complete_with_tool` / `resolve` / `resolve_model` uses the result
    and does not swallow `LlmError`s (no bare statement, no `_ =`, no `except ...: pass`).
(b) is arborescent.toml: only ring `llm` lists `anthropic` (checked here too, so a config edit
    cannot quietly undo it).
Each scanner is itself tested on snippets, so it cannot rot into a scan that finds nothing.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCAN_DIRS = ("src", "libs", "vendor", "scripts")
SKIP_PARTS = {".venv", "__pycache__", "node_modules", ".git"}
LLMHOST_DIR = ROOT / "libs" / "llmhost"  # the one place allowed to talk to a model

MODEL_SDKS = {
    "anthropic",
    "openai",
    "ollama",
    "cohere",
    "mistralai",
    "groq",
    "litellm",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langchain_anthropic",
    "vertexai",
    "google.generativeai",
    "google.genai",
    "transformers",
    "llama_cpp",
    "huggingface_hub",
}
MODEL_ENDPOINTS = (
    "11434",
    "api.anthropic.com",
    "api.openai.com",
    "openai.azure.com",
    "generativelanguage.googleapis.com",
    "api.mistral.ai",
    "api.cohere.com",
    "api.groq.com",
)
CALLS = {"complete_with_tool", "resolve", "resolve_model"}
BROAD = {"Exception", "BaseException", "LlmError"}


def _is_sdk(module: str) -> bool:
    return any(module == sdk or module.startswith(sdk + ".") for sdk in MODEL_SDKS)


def sdk_and_endpoint_violations(source: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [f"imports {a.name}" for a in node.names if _is_sdk(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            if _is_sdk(node.module):
                found.append(f"imports from {node.module}")
        elif isinstance(node, ast.Call) and _is_dynamic_import(node):
            found.append("dynamically imports a model SDK")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found += [f"names endpoint {e}" for e in MODEL_ENDPOINTS if e in node.value]
    return found


def _is_dynamic_import(node: ast.Call) -> bool:
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    first = node.args[0] if node.args else None
    return (
        name in {"import_module", "__import__"}
        and isinstance(first, ast.Constant)
        and isinstance(first.value, str)
        and _is_sdk(first.value)
    )


def _is_llm_call(node: ast.Call, from_llmhost: set[str]) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute):
        if func.attr == "complete_with_tool":
            return True
        return (
            func.attr in CALLS and isinstance(func.value, ast.Name) and func.value.id == "llmhost"
        )
    return isinstance(func, ast.Name) and func.id in from_llmhost


def _swallows(handler: ast.ExceptHandler) -> bool:
    caught = handler.type
    names = (
        {n.id for n in ast.walk(caught) if isinstance(n, ast.Name)} if caught is not None else set()
    )
    broad = caught is None or bool(names & BROAD)
    only_noop = all(
        isinstance(s, (ast.Pass, ast.Continue))
        or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
        or (isinstance(s, ast.Return) and s.value is None)
        for s in handler.body
    )
    return broad and only_noop


def discarded_call_violations(source: str) -> tuple[int, list[str]]:
    """Returns (number of llm call sites, violations)."""
    tree = ast.parse(source)
    from_llmhost = {
        (a.asname or a.name)
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module == "llmhost"
        for a in n.names
        if a.name in CALLS
    }
    parent: dict[ast.AST, ast.AST] = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    sites = 0
    found: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_llm_call(node, from_llmhost)):
            continue
        sites += 1
        up = parent.get(node)
        if isinstance(up, ast.Expr) and not _inside_raises(node, parent):
            found.append(f"line {node.lineno}: result discarded")
        elif isinstance(up, ast.Assign) and all(
            isinstance(t, ast.Name) and t.id == "_" for t in up.targets
        ):
            found.append(f"line {node.lineno}: result assigned to _")
        anc: ast.AST | None = up
        while anc is not None:
            if isinstance(anc, ast.Try) and any(_in(node, s) for s in anc.body):
                found += [
                    f"line {node.lineno}: error swallowed" for h in anc.handlers if _swallows(h)
                ]
            if isinstance(anc, ast.With) and any(_is_suppress(i.context_expr) for i in anc.items):
                found.append(f"line {node.lineno}: error suppressed")
            anc = parent.get(anc)
    return sites, found


def _inside_raises(node: ast.AST, parent: dict[ast.AST, ast.AST]) -> bool:
    """`with pytest.raises(...): resolve("bad")` -- the discard IS the assertion."""
    anc = parent.get(node)
    while anc is not None:
        if isinstance(anc, ast.With) and any(
            isinstance(i.context_expr, ast.Call)
            and getattr(i.context_expr.func, "attr", "") == "raises"
            for i in anc.items
        ):
            return True
        anc = parent.get(anc)
    return False


def _in(node: ast.AST, container: ast.AST) -> bool:
    return any(n is node for n in ast.walk(container))


def _is_suppress(expr: ast.expr) -> bool:
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    return (isinstance(func, ast.Name) and func.id == "suppress") or (
        isinstance(func, ast.Attribute) and func.attr == "suppress"
    )


def _python_files() -> list[Path]:
    files = []
    for top in SCAN_DIRS:
        base = ROOT / top
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if SKIP_PARTS & set(path.parts) or LLMHOST_DIR in path.parents:
                continue
            files.append(path)
    return files


# --------------------------------------------------------------------------- the real scans
def test_nothing_outside_llmhost_touches_a_model_sdk_or_endpoint() -> None:
    this = Path(__file__).resolve()
    bad = {
        str(p.relative_to(ROOT)): v
        for p in _python_files()
        if p.resolve() != this and (v := sdk_and_endpoint_violations(p.read_text()))
    }
    assert not bad, f"go through llmhost.Provider instead: {bad}"


def test_every_llm_call_uses_its_result_and_its_errors() -> None:
    total = 0
    bad: dict[str, list[str]] = {}
    for path in _python_files():
        sites, violations = discarded_call_violations(path.read_text())
        total += sites
        if violations:
            bad[str(path.relative_to(ROOT))] = violations
    assert total >= 1, "scanner found no llmhost call sites at all: it is probably broken"
    assert not bad, bad


def test_the_known_adapters_are_among_the_scanned_callers() -> None:
    for rel in (
        "src/adapter_events/src/last_newsletter_adapter_events/extractor.py",
        "src/adapter_summarizer/src/last_newsletter_adapter_summarizer/anthropic_summarizer.py",
    ):
        sites, _ = discarded_call_violations((ROOT / rel).read_text())
        assert sites >= 1, rel


def test_only_the_llm_ring_may_list_anthropic() -> None:
    config = tomllib.loads((ROOT / "arborescent.toml").read_text())
    rings = config["ring"]
    listing = {name for name, ring in rings.items() if "anthropic" in ring.get("external", [])}
    assert listing <= {"llm", "cli"}, listing  # cli is "*" by design
    assert "anthropic" in rings["llm"]["external"]
    assert "libs" not in listing
    assert config["classify"]["llmhost"] == "llm"
    for name in ("adapters", "libs", "core"):
        assert "anthropic" not in rings[name].get("external", [])


def test_llmhost_declares_the_only_model_sdk_dependency() -> None:
    for pyproject in ROOT.glob("*/*/pyproject.toml"):
        if pyproject.parent.name == "llmhost":
            continue
        deps = tomllib.loads(pyproject.read_text()).get("project", {}).get("dependencies", [])
        sdks = [d for d in deps if _is_sdk(d.split(">")[0].split("=")[0].split("[")[0].strip())]
        assert not sdks, f"{pyproject.relative_to(ROOT)} depends on a model SDK: {sdks}"


# --------------------------------------------------------------------------- scanner self-tests
@pytest.mark.parametrize(
    "source",
    [
        "import anthropic",
        "import openai.types",
        "from ollama import Client",
        "import importlib\nimportlib.import_module('anthropic')",
        "__import__('openai')",
        "URL = 'http://localhost:11434/api/chat'",
        "URL = f'https://api.anthropic.com/v1/{x}'",
    ],
)
def test_sdk_scanner_catches(source: str) -> None:
    assert sdk_and_endpoint_violations(source)


@pytest.mark.parametrize(
    "source",
    [
        "import json",
        "from llmhost import resolve",
        "x = 'anthropic'",
        "import httpx",
        "import importlib\nimportlib.import_module('json')",
    ],
)
def test_sdk_scanner_ignores_innocent_code(source: str) -> None:
    assert not sdk_and_endpoint_violations(source)


@pytest.mark.parametrize(
    "source",
    [
        "p.complete_with_tool(r)",
        "_ = p.complete_with_tool(r)",
        "from llmhost import resolve\nresolve('claude')",
        "import llmhost\nllmhost.resolve_model('x')",
        "try:\n    x = p.complete_with_tool(r)\nexcept Exception:\n    pass",
        "try:\n    x = p.complete_with_tool(r)\nexcept LlmError:\n    continue",
        "try:\n    x = p.complete_with_tool(r)\nexcept:\n    return",
        "with suppress(Exception):\n    x = p.complete_with_tool(r)",
        "import contextlib\nwith contextlib.suppress(Exception):\n    y = p.complete_with_tool(r)",
    ],
)
def test_call_scanner_catches(source: str) -> None:
    assert discarded_call_violations(source)[1]


@pytest.mark.parametrize(
    "source",
    [
        "x = p.complete_with_tool(r)",
        "return p.complete_with_tool(r).tool_input",
        "from llmhost import resolve\nprovider = resolve('claude')",
        "from pathlib import Path\nPath('.').resolve()",
        "try:\n    x = p.complete_with_tool(r)\nexcept LlmError as e:\n    raise Failed() from e",
        "try:\n    x = p.complete_with_tool(r)\nexcept KeyError:\n    pass",
        "with pytest.raises(LlmError):\n    p.complete_with_tool(r)",
    ],
)
def test_call_scanner_accepts_proper_use(source: str) -> None:
    assert not discarded_call_violations(source)[1]
