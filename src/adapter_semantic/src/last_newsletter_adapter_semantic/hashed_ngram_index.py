"""Local similar-event index: hashed character n-gram vectors persisted in SQLite.

Stdlib only, fully offline, deterministic. A hit means "possible duplicate": callers may
record a link for the owner to review but must never merge on a score alone.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import json
import math
import sqlite3
import unicodedata
import zlib
from collections import Counter
from datetime import date
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Hashable, Sequence
    from pathlib import Path

# Chosen on tests/fixtures/event_pairs.json; see docs/design/semantic-index.md.
DEFAULT_THRESHOLD = 0.6

_MAX_CHARS = 2000
_BUCKETS = 1 << 20
_NGRAM = 3
_DATE_UNKNOWN = 0.85
_DATE_ADJACENT = 0.9
_DATE_DIFFERENT = 0.45
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS event_vectors (id TEXT PRIMARY KEY, day TEXT, vec TEXT NOT NULL)"
)

Vector = dict[int, float]


class IndexableEvent(Protocol):
    """What the index reads from an event. Core's `Event` is expected to satisfy this shape
    (or be adapted to it at the wiring site)."""

    @property
    def id(self) -> Hashable: ...
    @property
    def title(self) -> str: ...
    @property
    def venue(self) -> str: ...
    @property
    def entities(self) -> Sequence[str]: ...
    @property
    def day(self) -> date | None: ...


def event_text(event: IndexableEvent) -> str:
    """Title (weighted by repetition) + venue + entities; the date is handled separately."""
    parts = [event.title, event.title, event.venue, *event.entities]
    return " ".join(p for p in parts if isinstance(p, str))


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text[: _MAX_CHARS * 2]).casefold()
    cleaned = "".join(c if c.isalnum() else " " for c in text)
    return " ".join(cleaned.split())[:_MAX_CHARS]


def _vectorize(text: str) -> Vector:
    norm = _normalize(text)
    if not norm:
        return {}
    counts: Counter[int] = Counter()
    for word in norm.split():
        counts[zlib.crc32(b"w:" + word.encode()) % _BUCKETS] += 1
        padded = f" {word} "
        for i in range(max(len(padded) - _NGRAM + 1, 0)):
            counts[zlib.crc32(padded[i : i + _NGRAM].encode()) % _BUCKETS] += 1
    weights = {k: 1.0 + math.log(v) for k, v in counts.items()}
    length = math.sqrt(sum(w * w for w in weights.values()))
    return {k: w / length for k, w in weights.items()}


def _cosine(a: Vector, b: Vector) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(k, 0.0) for k, w in a.items())


def _date_factor(a: date | None, b: date | None) -> float:
    if a is None or b is None:
        return _DATE_UNKNOWN
    gap = abs((a - b).days)
    if gap == 0:
        return 1.0
    return _DATE_ADJACENT if gap == 1 else _DATE_DIFFERENT


class HashedNgramIndex:
    """`SimilarEventIndex` backed by SQLite; vectors are cached in memory (thousands of rows)."""

    def __init__(
        self, path: Path | str = ":memory:", *, threshold: float = DEFAULT_THRESHOLD
    ) -> None:
        self._threshold = threshold
        self._db = sqlite3.connect(str(path))
        self._db.execute(_SCHEMA)
        self._db.commit()
        self._rows: dict[str, tuple[date | None, Vector]] = {}
        for ident, day, vec in self._db.execute("SELECT id, day, vec FROM event_vectors"):
            self._rows[ident] = (_parse_day(day), {int(k): v for k, v in json.loads(vec).items()})

    def close(self) -> None:
        self._db.close()

    def index(self, event: IndexableEvent) -> None:
        """Insert or replace the event's vector. Never raises on odd text."""
        ident = str(event.id)
        vec = _vectorize(event_text(event))
        day = event.day
        self._db.execute(
            "INSERT OR REPLACE INTO event_vectors (id, day, vec) VALUES (?, ?, ?)",
            (ident, day.isoformat() if day else None, json.dumps(vec)),
        )
        self._db.commit()
        self._rows[ident] = (day, vec)

    def similar(self, candidate: IndexableEvent, *, limit: int = 5) -> list[tuple[str, float]]:
        """Indexed events scoring >= threshold against `candidate`, best first.

        Scores are in [0, 1] and deterministic; ties break on id. The candidate's own id is
        excluded. These are possible duplicates only.
        """
        if limit <= 0:
            return []
        own = str(candidate.id)
        vec = _vectorize(event_text(candidate))
        if not vec:
            return []
        scored = []
        for ident, (day, other) in self._rows.items():
            if ident == own:
                continue
            score = round(
                min(1.0, max(0.0, _cosine(vec, other) * _date_factor(candidate.day, day))), 6
            )
            if score >= self._threshold:
                scored.append((ident, score))
        scored.sort(key=lambda p: (-p[1], p[0]))
        return scored[:limit]


def _parse_day(raw: str | None) -> date | None:
    return date.fromisoformat(raw) if raw is not None else None
