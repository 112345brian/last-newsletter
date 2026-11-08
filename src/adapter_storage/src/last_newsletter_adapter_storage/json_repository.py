"""Concrete DigestRepository: one JSON file per digest in a directory on disk.

No database server — this is meant to run on the same machine as the CLI,
same as a flat-file store for a local tool. Swap this adapter for a SQLite-
or Postgres-backed one later without touching core or adapter_web, if a flat
directory of files ever stops being enough.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import json
import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from ranked_digest.entities import Cadence, Digest, Theme, digest_slug

if TYPE_CHECKING:
    from pathlib import Path


# Letters, digits, `_` and `-` only: no separators, no dots, so no path can be spelled with it.
_SLUG_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


def _theme_to_dict(theme: Theme) -> dict[str, Any]:
    return {
        "title": theme.title,
        "summary": theme.summary,
        "source_count": theme.source_count,
        "source_message_ids": list(theme.source_message_ids),
        "theme_key": theme.theme_key,
        "relevant_until": theme.relevant_until.isoformat() if theme.relevant_until else None,
        "first_seen": theme.first_seen.isoformat() if theme.first_seen else None,
        "streak": theme.streak,
        "carried_forward": theme.carried_forward,
        "personal_weight": theme.personal_weight,
    }


def _theme_from_dict(data: dict[str, Any]) -> Theme:
    return Theme(
        title=data["title"],
        summary=data["summary"],
        source_count=data["source_count"],
        source_message_ids=tuple(data["source_message_ids"]),
        theme_key=data["theme_key"],
        relevant_until=(
            date.fromisoformat(data["relevant_until"]) if data["relevant_until"] else None
        ),
        first_seen=date.fromisoformat(data["first_seen"]) if data["first_seen"] else None,
        streak=data["streak"],
        carried_forward=data["carried_forward"],
        personal_weight=data["personal_weight"],
    )


def _to_dict(digest: Digest) -> dict[str, Any]:
    return {
        "period_start": digest.period_start.isoformat(),
        "period_end": digest.period_end.isoformat(),
        "cadence": digest.cadence.value,
        "total_messages": digest.total_messages,
        "total_sources": digest.total_sources,
        "themes": [_theme_to_dict(theme) for theme in digest.themes],
    }


def _from_dict(data: dict[str, Any]) -> Digest:
    return Digest(
        period_start=datetime.fromisoformat(data["period_start"]),
        period_end=datetime.fromisoformat(data["period_end"]),
        cadence=Cadence(data["cadence"]),
        total_messages=data["total_messages"],
        total_sources=data["total_sources"],
        themes=tuple(_theme_from_dict(t) for t in data["themes"]),
    )


class JsonDigestRepository:
    """Implements ranked_digest.ports.DigestRepository."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, digest: Digest) -> str:
        slug = digest_slug(digest)
        path = self._base_dir / f"{slug}.json"
        path.write_text(json.dumps(_to_dict(digest), indent=2))
        return slug

    def list_recent(self, limit: int = 20) -> list[tuple[str, Digest]]:
        paths = sorted(self._base_dir.glob("*.json"), reverse=True)[:limit]
        return [(path.stem, _from_dict(json.loads(path.read_text()))) for path in paths]

    def get(self, slug: str) -> Digest | None:
        # A slug is opaque to callers, but adapter_web forwards a URL segment here, so refuse
        # anything that isn't the shape `digest_slug` produces before it becomes a path.
        if _SLUG_PATTERN.fullmatch(slug) is None:
            return None
        path = self._base_dir / f"{slug}.json"
        if not path.is_file():
            return None
        return _from_dict(json.loads(path.read_text()))
