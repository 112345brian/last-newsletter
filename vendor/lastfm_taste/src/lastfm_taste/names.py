"""Comparing names: the one normalization genres and artist names share. Pure, no I/O."""

from __future__ import annotations

__arbor__ = {"ring": "core"}

import re
import unicodedata


def normalize_text(text: str) -> str:
    """Case, accent, width and punctuation-insensitive form used to compare names and tags."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    decomposed = unicodedata.normalize("NFKD", folded)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[\W_]+", " ", stripped).split())


def normalize_without_leading_article(name: str) -> str:
    """`normalize_text`, minus one leading "the", for comparing names.

    "The Echo", "the ECHO!" and "Echo" compare equal. Only a leading article goes (so "Lodge of the
    Room" and "Thebes" are untouched), and a name that is only the article keeps it, so a name is
    never normalized to nothing and mistaken for a missing one.
    """
    words = normalize_text(name).split()
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    return " ".join(words)
