"""Literal whole-word term matching: no stemming, no fuzziness, no model.

Terms are normalized (NFC, whitespace collapsed, casefolded) and matched against
NFC-normalized text as WHOLE words: not preceded or followed by a letter, digit
or underscore, so "brother" does not match "brotherhood" but does match
"brother's", "Brother," or "my-brother". Regex metacharacters in a term are
literal; spaces in a term match any whitespace run.

Pure functions; no imports beyond the standard library. Originally written for
a personal knowledge base (so a keyword list and an entity-alias list could
never disagree about what "mentions" means), factored out here because the
same problem — does this piece of text literally say this term — comes up
anywhere text is matched against a vocabulary, not just there.
"""

from __future__ import annotations

import functools
import re
import unicodedata

__all__ = ["find_terms", "normalize_term"]


def normalize_term(raw: str) -> str:
    """The canonical form of a term. Raises ValueError (clear message) when the *content* could
    never match a whole word: blank, control characters, or no letters/digits at all. A value
    that is not a string at all is a caller bug, not bad content, and raises TypeError."""
    if not isinstance(raw, str):
        msg = f"term must be a string, got {type(raw).__name__}"
        raise TypeError(msg)
    term = " ".join(unicodedata.normalize("NFC", raw).split()).casefold()
    if not term:
        msg = "is empty or blank"
        raise ValueError(msg)
    if any(unicodedata.category(c) in ("Cc", "Cf") for c in term):
        msg = f"{raw!r} contains control characters"
        raise ValueError(msg)
    if not re.search(r"\w", term):
        msg = f"{raw!r} has no letters or digits, so it can never match a whole word"
        raise ValueError(msg)
    return term


@functools.lru_cache(maxsize=512)
def _term_re(term: str) -> re.Pattern[str]:
    body = r"\s+".join(re.escape(part) for part in term.split(" "))
    return re.compile(r"(?<!\w)" + body + r"(?!\w)", re.IGNORECASE)


def find_terms(text: str, terms: list[str]) -> list[str]:
    """The `terms` (already normalized) found as whole words in `text`, in list order."""
    if not text:
        return []
    normalized_text = unicodedata.normalize("NFC", text)
    return [t for t in terms if _term_re(t).search(normalized_text)]
