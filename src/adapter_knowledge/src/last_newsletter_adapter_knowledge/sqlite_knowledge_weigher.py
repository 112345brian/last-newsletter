"""Reads a personal knowledge.db (schema: https://github.com/112345brian/knowledge) read-only,
translating "do I have facts about this candidate, and how many corroborate it mattering to
me" into the float ranked_digest.ports.RelevanceWeigher expects.

Deliberately NOT a dependency on the `knowledge` project's own (unpublished, internal) Python
code — that package exists to be an application, not a library, and has no stability promise
for other projects to import. Its *schema* is the stable, versioned contract instead (see its
own schema.sql: "the single source of truth for the core structure", `PRAGMA user_version`
bumped on every structural change, enforced by its own test suite). This module reads against
that contract directly: a normalized exact match against `entities.name_norm`/
`entity_aliases.alias_norm` (the same literal, case-insensitive whole-name matching `knowledge`
itself uses for this — via the standalone `text-match` package, factored out of `knowledge`'s own
`textmatch.py` once this became a second real consumer of the identical logic), counting active,
`kind='preference'` facts linked to that entity. A changed schema is a loud failure
(`SchemaVersionMismatchError`), never a silent wrong answer.

This is one possible translation, not the only one: a different RelevanceWeigher reading a
raw scrobble/listening-history export instead of this fact database might weigh a candidate
by play count or recency rather than by how many preference facts cite it. Nothing about
last_newsletter_core or BuildDigestUseCase needs to change to add one.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import sqlite3
from typing import TYPE_CHECKING

from text_match import normalize_term

if TYPE_CHECKING:
    from pathlib import Path

# The knowledge.db schema version this query is written against (schema.sql's own
# `PRAGMA user_version`). Bump only after checking the query below still matches the new schema.
_EXPECTED_SCHEMA_VERSION = 4

_QUERY = """
SELECT COUNT(DISTINCT f.id)
FROM facts f
JOIN fact_entities fe ON fe.fact_id = f.id
JOIN entities e ON e.id = fe.entity_id
LEFT JOIN entity_aliases ea ON ea.entity_id = e.id
LEFT JOIN subjects s ON s.id = f.subject_id
WHERE (e.name_norm = :candidate OR ea.alias_norm = :candidate)
  AND f.kind = 'preference'
  AND f.status = 'active'
  AND (:subject_name IS NULL OR s.name = :subject_name)
"""


class SchemaVersionMismatchError(RuntimeError):
    """knowledge.db's schema has moved since this query was written against it
    (_EXPECTED_SCHEMA_VERSION). Raised rather than silently querying a changed
    schema and risking a wrong (or just-absent) answer."""


class SqliteKnowledgeWeigher:
    """Implements ranked_digest.ports.RelevanceWeigher.

    `weight_per_fact` is this adapter's translation knob: how much one corroborating
    preference fact about a matched entity should move a theme's ranking. The default (3.0)
    mirrors BuildDigestUseCase's own per-period streak increment, so one solid personal match
    carries roughly the same weight as one extra period of recurrence — a starting point, not
    a tuned constant; adjust it per how much this signal should actually matter to you.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        subject_name: str | None = None,
        weight_per_fact: float = 3.0,
    ) -> None:
        self._db_path = db_path
        self._subject_name = subject_name
        self._weight_per_fact = weight_per_fact

    def weight_for(self, candidate: str) -> float:
        try:
            normalized = normalize_term(candidate)
        except ValueError:
            # A candidate with nothing to match on (blank, no letters/digits) -- no personal
            # signal, not an error worth failing the whole digest build over.
            return 0.0
        uri = f"file:{self._db_path}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version != _EXPECTED_SCHEMA_VERSION:
                msg = (
                    f"knowledge.db is schema version {version}, expected "
                    f"{_EXPECTED_SCHEMA_VERSION} -- check schema.sql and this query "
                    "before trusting its answers"
                )
                raise SchemaVersionMismatchError(msg)
            row = conn.execute(
                _QUERY, {"candidate": normalized, "subject_name": self._subject_name}
            ).fetchone()
            match_count = int(row[0])
            return match_count * self._weight_per_fact
