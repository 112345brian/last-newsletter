from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from semantic_support import Ev

from last_newsletter_adapter_semantic import DEFAULT_THRESHOLD, HashedNgramIndex

FIXTURE = Path(__file__).parent / "fixtures" / "event_pairs.json"
MIN_PRECISION = 0.9
MIN_RECALL = 0.9


def _ev(ident: str, raw: dict[str, Any]) -> Ev:
    return Ev(
        ident,
        str(raw["title"]),
        str(raw["venue"]),
        tuple(str(e) for e in raw["entities"]),
        date.fromisoformat(str(raw["day"])),
    )


def evaluate(threshold: float) -> tuple[float, float, int]:
    tp = fp = fn = 0
    pairs = json.loads(FIXTURE.read_text())
    for pair in pairs:
        idx = HashedNgramIndex(threshold=threshold)
        idx.index(_ev("a", pair["a"]))
        hit = bool(idx.similar(_ev("b", pair["b"])))
        same = pair["label"] == "same"
        tp += int(hit and same)
        fp += int(hit and not same)
        fn += int(same and not hit)
        idx.close()
    return tp / max(tp + fp, 1), tp / max(tp + fn, 1), len(pairs)


def test_fixture_size() -> None:
    assert evaluate(DEFAULT_THRESHOLD)[2] >= 25


def test_precision_recall_at_default_threshold() -> None:
    precision, recall, _ = evaluate(DEFAULT_THRESHOLD)
    assert precision >= MIN_PRECISION, precision
    assert recall >= MIN_RECALL, recall


def test_same_title_different_date_scores_below_same_date() -> None:
    idx = HashedNgramIndex()
    idx.index(Ev("1", "Jon Hopkins live", "Steel", day=date(2026, 12, 12)))
    same = idx.similar(Ev("q", "Jon Hopkins live", "Steel", day=date(2026, 12, 12)))
    idx2 = HashedNgramIndex()
    idx2.index(Ev("1", "Jon Hopkins live", "Steel", day=date(2026, 12, 12)))
    other = idx2.similar(Ev("q", "Jon Hopkins live", "Steel", day=date(2027, 3, 1)))
    assert same
    assert not other


def test_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "i.sqlite"
    first = HashedNgramIndex(path)
    first.index(Ev("uuid-1", "Four Tet at Printworks", "Printworks", day=date(2026, 11, 20)))
    first.close()
    second = HashedNgramIndex(path)
    hits = second.similar(Ev("new", "Four Tet @ Printworks", "Printworks", day=date(2026, 11, 20)))
    assert [i for i, _ in hits] == ["uuid-1"]


def test_cold_start_and_query_are_fast_for_thousands(tmp_path: Path) -> None:
    path = tmp_path / "big.sqlite"
    idx = HashedNgramIndex(path)
    for n in range(3000):
        idx.index(
            Ev(
                str(n),
                f"Event number {n} with act {n * 7}",
                f"Venue {n % 50}",
                day=date(2026, 1, 1),
            )
        )
    idx.close()
    t0 = time.perf_counter()
    idx = HashedNgramIndex(path)
    idx.similar(Ev("q", "Event number 42 with act 294", "Venue 42", day=date(2026, 1, 1)))
    assert time.perf_counter() - t0 < 5
