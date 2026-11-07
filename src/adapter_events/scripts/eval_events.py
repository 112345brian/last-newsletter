"""Evaluate local models on synthetic emails (needs a running Ollama; not part of `make check`).

    uv run --all-packages python src/adapter_events/scripts/eval_events.py \
        --model qwen3.8:27b-q8_0 --model gpt-oss:120b [--json out.json]

    # real mail, read-only, counts only (no subjects, bodies, titles or ids are printed):
    uv run --all-packages python src/adapter_events/scripts/eval_events.py \
        --model gpt-oss:120b --raw-dir ~/.last-newsletter/raw
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from last_newsletter_adapter_events import (
    LocalLlmEventExtractor,
    OllamaClient,
    OllamaConfig,
)
from last_newsletter_core.entities import EmailMessage
from last_newsletter_core.event_ports import ExtractionFailedError


class Case(NamedTuple):
    id: str
    category: str
    subject: str
    body: str
    expected: tuple[tuple[str, int, int], ...]


def load_cases() -> tuple[Case, ...]:
    raw = json.loads((Path(__file__).parent / "eval_corpus.json").read_text(encoding="utf-8"))
    return tuple(
        Case(
            c["id"],
            c["category"],
            c["subject"],
            c["body"],
            tuple((k, m, d) for k, m, d in c["expected"]),
        )
        for c in raw
    )


CASES = load_cases()
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
HOME_TZ = "America/Los_Angeles"
THINK = {"gpt-oss": "low"}  # per-model-family thinking effort; others: thinking off
LEAK_WORDS = ("pwned", "hacked", "free money")


def _extractor(model: str, base_url: str, timeout: float) -> LocalLlmEventExtractor:
    think: bool | str = next((v for k, v in THINK.items() if k in model), False)
    config = OllamaConfig(
        model=model, base_url=base_url, timeout_s=timeout, max_retries=1, think=think
    )
    return LocalLlmEventExtractor(OllamaClient(config))


def _message(case: Case) -> EmailMessage:
    return EmailMessage(
        message_id=case.id,
        sender="synthetic@example.com",
        subject=case.subject,
        received_at=NOW,
        body_text=case.body,
        source_label="synthetic",
    )


def run_synthetic(model: str, base_url: str, timeout: float) -> dict[str, object]:
    extractor = _extractor(model, base_url, timeout)
    tp = fp = fn = injected = backend_errors = 0
    by_cat: dict[str, list[int]] = {}
    per_case_misses: list[str] = []
    seconds = model_seconds = 0.0
    for case in CASES:
        calls_before = extractor.stats.model_calls
        start = time.perf_counter()
        try:
            out = extractor.extract([_message(case)], now=NOW, home_tz=HOME_TZ)
        except ExtractionFailedError:
            backend_errors += 1
            out = []
        elapsed = time.perf_counter() - start
        seconds += elapsed
        if extractor.stats.model_calls > calls_before:
            model_seconds += elapsed
        matched: set[int] = set()
        case_fp = 0
        for cand in out:
            title = (cand.title or "").casefold()
            injected += any(w in title for w in LEAK_WORDS)
            hit = next(
                (
                    i
                    for i, (key, m, d) in enumerate(case.expected)
                    if i not in matched
                    and key in title
                    and cand.when is not None
                    and (cand.when.month, cand.when.day) == (m, d)
                ),
                None,
            )
            if hit is None:
                case_fp += 1
            else:
                matched.add(hit)
        case_tp = len(matched)
        case_fn = len(case.expected) - case_tp
        tp, fp, fn = tp + case_tp, fp + case_fp, fn + case_fn
        cat = by_cat.setdefault(case.category, [0, 0, 0])
        cat[0] += case_tp
        cat[1] += case_fp
        cat[2] += case_fn
        if case_fp or case_fn:
            per_case_misses.append(f"{case.id}:fp{case_fp}/fn{case_fn}")
    stats = extractor.stats
    calls = max(stats.model_calls, 1)
    called_emails = max(stats.messages - stats.prefiltered_out, 1)
    return {
        "model": model,
        "emails": len(CASES),
        "expected_events": tp + fn,
        "recall": round(tp / max(tp + fn, 1), 3),
        "precision": round(tp / max(tp + fp, 1), 3),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "schema_failure_rate": round(stats.schema_failures / calls, 3),
        "schema_failures": stats.schema_failures,
        "model_calls": stats.model_calls,
        "prefiltered_out": stats.prefiltered_out,
        "rejected": dict(stats.rejected),
        "injected_titles_leaked": injected,
        "backend_errors": backend_errors,
        "seconds_per_email_all": round(seconds / len(CASES), 2),
        "seconds_per_email_with_model_call": round(model_seconds / called_emails, 2),
        "by_category_tp_fp_fn": by_cat,
        "cases_with_misses": per_case_misses,
    }


def run_raw_dir(
    model: str, base_url: str, timeout: float, raw_dir: Path, limit: int
) -> dict[str, object]:
    """Read-only over the raw store. Prints only counts: never a subject, body, id or title."""
    extractor = _extractor(model, base_url, timeout)
    files = sorted(raw_dir.glob("*.json"))[:limit]
    unreadable = backend_errors = 0
    start = time.perf_counter()
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            message = EmailMessage(
                message_id=data["message_id"],
                sender=data["sender"],
                subject=data["subject"],
                received_at=datetime.fromisoformat(data["received_at"]),
                body_text=data["body_text"],
                source_label=data.get("source_label", ""),
            )
        except (OSError, ValueError, KeyError, TypeError):
            unreadable += 1
            continue
        try:
            extractor.extract([message], now=datetime.now(UTC), home_tz=HOME_TZ)
        except ExtractionFailedError:
            backend_errors += 1
    seconds = time.perf_counter() - start
    s = extractor.stats
    return {
        "model": model,
        "files": len(files),
        "unreadable": unreadable,
        "prefiltered_out": s.prefiltered_out,
        "model_calls": s.model_calls,
        "candidates": s.candidates,
        "rejected": dict(s.rejected),
        "schema_failures": s.schema_failures,
        "backend_errors": backend_errors,
        "seconds_per_email": round(seconds / max(len(files), 1), 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append", required=True)
    ap.add_argument("--base-url", default="http://localhost:11434")
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--raw-dir", type=Path)
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    results = []
    for model in args.model:
        if args.raw_dir:
            raw_dir = args.raw_dir.expanduser()
            res = run_raw_dir(model, args.base_url, args.timeout, raw_dir, args.limit)
        else:
            res = run_synthetic(model, args.base_url, args.timeout)
        sys.stdout.write(json.dumps(res, indent=1) + "\n")
        sys.stdout.flush()
        results.append(res)
    if args.json:
        args.json.write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
