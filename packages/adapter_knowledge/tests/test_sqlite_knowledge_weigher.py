"""Tests build their own minimal fixture DB — just the columns the real query touches,
not a copy of knowledge's actual schema.sql — so this suite stays portable and never
reads anything from the sibling `knowledge` checkout."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from last_newsletter_adapter_knowledge.sqlite_knowledge_weigher import (
    SchemaVersionMismatchError,
    SqliteKnowledgeWeigher,
)

if TYPE_CHECKING:
    from pathlib import Path

_SCHEMA = """
CREATE TABLE entities (id INTEGER PRIMARY KEY, name_norm TEXT NOT NULL UNIQUE);
CREATE TABLE entity_aliases (entity_id INTEGER NOT NULL, alias_norm TEXT NOT NULL UNIQUE);
CREATE TABLE subjects (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE facts (
    id INTEGER PRIMARY KEY, subject_id INTEGER, kind TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE fact_entities (fact_id INTEGER NOT NULL, entity_id INTEGER NOT NULL);
"""


def _make_db(tmp_path: Path, *, schema_version: int = 4) -> Path:
    db_path = tmp_path / "knowledge.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    conn.execute(f"PRAGMA user_version = {schema_version}")
    conn.commit()
    conn.close()
    return db_path


def _add_entity(db_path: Path, *, name_norm: str, aliases: tuple[str, ...] = ()) -> int:
    conn = sqlite3.connect(db_path)
    entity_id = conn.execute("INSERT INTO entities (name_norm) VALUES (?)", (name_norm,)).lastrowid
    for alias in aliases:
        conn.execute(
            "INSERT INTO entity_aliases (entity_id, alias_norm) VALUES (?, ?)", (entity_id, alias)
        )
    conn.commit()
    conn.close()
    return entity_id


def _add_subject(db_path: Path, name: str) -> int:
    conn = sqlite3.connect(db_path)
    subject_id = conn.execute("INSERT INTO subjects (name) VALUES (?)", (name,)).lastrowid
    conn.commit()
    conn.close()
    return subject_id


def _add_fact(
    db_path: Path, *, entity_id: int, subject_id: int | None, kind: str, status: str = "active"
) -> None:
    conn = sqlite3.connect(db_path)
    fact_id = conn.execute(
        "INSERT INTO facts (subject_id, kind, status) VALUES (?, ?, ?)", (subject_id, kind, status)
    ).lastrowid
    conn.execute(
        "INSERT INTO fact_entities (fact_id, entity_id) VALUES (?, ?)", (fact_id, entity_id)
    )
    conn.commit()
    conn.close()


def test_no_matching_entity_returns_zero(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    weigher = SqliteKnowledgeWeigher(db_path)

    assert weigher.weight_for("Nonexistent Artist") == 0.0


def test_weighs_by_count_of_preference_facts(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    music = _add_subject(db_path, "music")
    entity_id = _add_entity(db_path, name_norm="artist x")
    _add_fact(db_path, entity_id=entity_id, subject_id=music, kind="preference")
    _add_fact(db_path, entity_id=entity_id, subject_id=music, kind="preference")
    weigher = SqliteKnowledgeWeigher(db_path, weight_per_fact=2.0)

    assert weigher.weight_for("Artist X") == 4.0


def test_matches_via_normalized_alias(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    entity_id = _add_entity(db_path, name_norm="the real name", aliases=("stage name",))
    _add_fact(db_path, entity_id=entity_id, subject_id=None, kind="preference")
    weigher = SqliteKnowledgeWeigher(db_path, weight_per_fact=1.0)

    assert weigher.weight_for("  Stage   Name  ") == 1.0


def test_non_preference_facts_do_not_count(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    entity_id = _add_entity(db_path, name_norm="artist x")
    _add_fact(db_path, entity_id=entity_id, subject_id=None, kind="observation")
    weigher = SqliteKnowledgeWeigher(db_path)

    assert weigher.weight_for("Artist X") == 0.0


def test_inactive_facts_do_not_count(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    entity_id = _add_entity(db_path, name_norm="artist x")
    _add_fact(db_path, entity_id=entity_id, subject_id=None, kind="preference", status="retracted")
    weigher = SqliteKnowledgeWeigher(db_path)

    assert weigher.weight_for("Artist X") == 0.0


def test_subject_filter_excludes_facts_under_a_different_subject(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    cooking = _add_subject(db_path, "cooking")
    entity_id = _add_entity(db_path, name_norm="artist x")
    _add_fact(db_path, entity_id=entity_id, subject_id=cooking, kind="preference")
    weigher = SqliteKnowledgeWeigher(db_path, subject_name="music", weight_per_fact=5.0)

    assert weigher.weight_for("Artist X") == 0.0


def test_schema_version_mismatch_raises(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path, schema_version=999)
    weigher = SqliteKnowledgeWeigher(db_path)

    with pytest.raises(SchemaVersionMismatchError):
        weigher.weight_for("Artist X")
