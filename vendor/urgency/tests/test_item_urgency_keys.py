"""The row keys ``item_urgency`` reads are exactly the ones ``UrgencyFields`` declares (#1548), and its decisions
hold for each: closing date, posted date, first-seen date, passed, none."""
from __future__ import annotations

import ast
import inspect
from datetime import date

import pytest

from urgency import item_urgency as module
from urgency.item_urgency import UrgencyFields, item_urgency
from urgency.survival_curve import SurvivalCurve

CURVE = SurvivalCurve(points=((0, 1.0), (7, 1.0), (22, 0.71), (45, 0.24), (75, 0.22), (90, 0.15)))
TODAY = date(2026, 11, 5)


def _keys_read() -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
        and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
    }


def test_the_keys_read_are_exactly_the_declared_contract():
    assert _keys_read() == set(UrgencyFields.__annotations__)


@pytest.mark.parametrize("row, kind, remaining", [
    ({"closing_date": "2026-11-08"}, "deadline", 3),
    ({"closing_date": "2026-11-08T23:00:00Z"}, "deadline", 3),
    ({"closing_date": "2026-11-01"}, "none", 10 ** 9),
    ({"closing_date": "2026-11-08", "date_posted": "2026-01-01"}, "deadline", 3),
    ({"date_posted": "2026-11-05"}, "age", None),
    ({"first_seen_at": "2026-11-05"}, "age", None),
    ({"date_posted": "garbage", "first_seen_at": "2026-11-05"}, "age", None),
    ({}, "none", 10 ** 9),
    ({"closing_date": None, "date_posted": ""}, "none", 10 ** 9),
])
def test_each_key_decides_as_documented(row, kind, remaining):
    got = item_urgency(row, TODAY, CURVE)
    assert got.kind == kind
    if remaining is not None:
        assert got.remaining == remaining
