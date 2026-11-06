"""Pinned outputs of the text kinds and of the org key (with an injected suffix set)."""
from __future__ import annotations

import pytest

from text_normalize import normalize, normalize_org

SUFFIXES = frozenset({"inc", "llc", "ltd", "co", "corp"})


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        ("text", "  ANALYST   ii ", "analyst ii"),
        ("text", "R&D Lead (Remote)", "r d lead remote"),
        ("text", "a\u0000b", "a b"),
        ("text", None, ""),
        ("space", "  Foo,   BAR \n", "foo, bar"),
        ("fold", "Stra\u00dfe  X", "strasse x"),
        ("words", "Caf\u00e9 \u2014 Bar", "caf bar"),
        ("slug", " Hello, World! ", "hello_world"),
    ],
)
def test_text_kinds(kind: str, raw: object, expected: str) -> None:
    assert normalize(raw, kind) == expected  # type: ignore[arg-type]


def test_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="unknown normalize kind"):
        normalize("x", "org")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        (None, ""),
        ("Fundaci\u00f3n Foo", "fundacion foo"),
        ("Booz Allen & Hamilton", "booz allen and hamilton"),
        ("The Urban Institute", "urban institute"),
        ("U.S. Dept", "dept"),
        ("US Foods", "us foods"),
        ("The Company", "company"),
        ("Co.", "co"),
        ("Ipsos in US", "ipsos"),
        ("Ipsos in the United States", "ipsos"),
        ("U.S. Environmental Protection Agency (EPA)", "environmental protection agency"),
        ("Doctors Without Borders (USA)", "doctors without borders usa"),
        ("Foo Co., Ltd.", "foo"),
        ("Mathematica Policy Research, LLC", "mathematica policy research"),
    ],
)
def test_org_key(raw: object, expected: str) -> None:
    assert normalize_org(raw, legal_suffixes=SUFFIXES) == expected


def test_suffix_set_is_the_callers() -> None:
    assert normalize_org("Foo Inc.", legal_suffixes=frozenset()) == "foo inc"
