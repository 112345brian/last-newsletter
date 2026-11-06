"""The identity ladder on plain items, with no job vocabulary (the job rules are pinned in tests/test_job_dedupe.py)."""
from __future__ import annotations

from dataclasses import dataclass

from identity_dedupe.ladder import dedupe, dedupe_grouped


@dataclass(frozen=True)
class Item:
    id: str
    identity: tuple[str, str] = ("", "")
    canonical_key: str = ""
    resolved_url: str | None = None
    is_direct: bool = False
    detail_score: tuple[int, ...] = (0,)


def _strip(url: str) -> str:
    return url.split("?")[0].rstrip("/")


def ids(items):
    return [i.id for i in items]


def test_the_same_id_collapses_and_the_more_detailed_copy_survives():
    out = dedupe([Item("a", detail_score=(1,)), Item("a", detail_score=(5,))], normalize_url=_strip)
    assert [i.detail_score for i in out] == [(5,)]


def test_the_injected_normalizer_decides_when_two_urls_are_the_same():
    a, b = Item("a", resolved_url="https://x/y?utm=1"), Item("b", resolved_url="https://x/y/")
    assert ids(dedupe([a, b], normalize_url=_strip)) == ["a"]
    assert ids(dedupe([a, b], normalize_url=lambda u: u)) == ["a", "b"]


def test_blank_title_evidence_never_merges_two_items():
    assert ids(dedupe([Item("a", ("o", "")), Item("b", ("o", ""))], normalize_url=_strip)) == ["a", "b"]


def test_direct_items_with_one_title_stay_apart_and_an_ambiguous_loose_copy_is_kept():
    d1, d2 = Item("d1", ("o", "t"), is_direct=True), Item("d2", ("o", "t"), is_direct=True)
    loose = Item("l", ("o", "t"))
    assert ids(dedupe([d1, d2, loose], normalize_url=_strip)) == ["d1", "d2", "l"]


def test_a_loose_copy_folds_into_the_one_direct_item_with_its_title():
    d, loose = Item("d", ("o", "t"), is_direct=True), Item("l", ("o", "t"))
    assert ids(dedupe([loose, d], normalize_url=_strip)) == ["d"]
    assert ids(dedupe([d, loose], normalize_url=_strip)) == ["d"]


def test_a_title_with_a_trailing_code_matches_the_bare_title():
    assert len(dedupe([Item("a", ("o", "Analyst")), Item("b", ("o", "Analyst 24-001"))], normalize_url=_strip)) == 1


def test_grouped_members_include_the_survivor_in_input_order():
    a, b = Item("a", canonical_key="k", detail_score=(1,)), Item("b", canonical_key="k", detail_score=(2,))
    [(survivor, members)] = dedupe_grouped([a, b], normalize_url=_strip)
    assert survivor is b and members == (a, b)
