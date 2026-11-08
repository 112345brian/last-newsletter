"""Text normalizers for comparison and dedup keys: ``normalize(text, kind=...)`` and ``normalize_org(name, ...)``.

The outputs feed persisted keys, so a change to a kind re-keys stored rows; ``tests/test_keys.py`` pins them.

Kinds of ``normalize`` (a closed set, each a whole named behaviour, not independent switches):

- ``"text"``: lowercase, punctuation to spaces, whitespace collapsed. For titles and any free text.
- ``"space"``: lowercase, whitespace runs to one space, ends trimmed; punctuation kept. For comparing free text.
- ``"fold"``: like ``space`` but ``casefold`` (so "Straße" == "STRASSE"). For comparing text across sources.
- ``"words"``: lowercase, every run of non-``[a-z0-9]`` to one space, trimmed. ASCII-only (accents are separators).
- ``"slug"``: like ``words`` but joined with ``_``; a stable identifier.

``normalize_org`` is the employer-name key: strips accents, ``&`` -> ``and``, a leading "The" or "U.S.", a scraped
trailing "in US", an initialism restating the name, and trailing legal suffixes (supplied by the caller); never
empties the key.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Set as AbstractSet
from typing import Literal, get_args

NormalizeKind = Literal["text", "space", "fold", "words", "slug"]

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: object, kind: NormalizeKind = "text") -> str:
    """The *kind* key for *text*; ``None`` is blank. An unknown *kind* raises ``ValueError``."""
    s = "" if text is None else str(text)
    if kind == "text":
        return _normalize_text(s)
    if kind == "space":
        return _WHITESPACE.sub(" ", s.lower()).strip()
    if kind == "fold":
        return " ".join(s.casefold().split())
    if kind == "words":
        return _NON_ALNUM.sub(" ", s.lower()).strip()
    if kind == "slug":
        return _NON_ALNUM.sub("_", s.strip().lower()).strip("_")
    raise ValueError(f"unknown normalize kind {kind!r} (expected one of {get_args(NormalizeKind)})")


def _normalize_text(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    s = s.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


# Some job sites render US company pages as "<Name> in US" (or "in USA" /
# "in United States") in the scraped org field -- a display quirk of that one
# source, not a real qualifier on the org's identity, so it must not survive
# into the dedup key ("Ipsos in US" vs "Ipsos" is the same employer).
_IN_COUNTRY_SUFFIX_RE = re.compile(
    r"\s+in\s+(the\s+)?(us|usa|u\.s\.a?\.?|united states)\s*$", re.IGNORECASE
)

# A trailing parenthetical that is exactly an acronym of the words before it
# ("Environmental Protection Agency (EPA)") is the org restating its own
# initialism, not a distinguishing qualifier -- unlike "(Remote)" or
# "(USA)" tacked onto an otherwise-unrelated initials, which the org kind
# must NOT collapse away. Matched conservatively: the parenthetical's letters
# have to equal the initials of the preceding words exactly, so a paren that
# happens to also be all-caps but isn't actually derived from the name (e.g.
# "Doctors Without Borders (USA)") is left alone.
_TRAILING_PAREN_RE = re.compile(r"^(.*\S)\s*\(([A-Za-z][A-Za-z.&]{1,9})\)\s*$")


def _org_tokens(text: str) -> list[str]:
    """Shared tokenizer step of the ``org`` kind: NFKD, lowercase, ``&``
    → ``and``, punctuation → whitespace, drop a leading article, drop a
    leading "U.S." (rendered as two single-letter tokens once punctuation is
    stripped) -- but never a bare "us"/"usa" token, which is left alone since
    that's plausibly part of a real name ("US Foods") rather than the
    country-prefix noise "U.S. Environmental Protection Agency" carries.
    """
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.lower().replace("&", " and ")
    t = re.sub(r"[^0-9a-z\s]", " ", t)
    tokens = t.split()
    if len(tokens) > 1 and tokens[0] == "the":
        tokens = tokens[1:]
    if len(tokens) > 2 and tokens[0] == "u" and tokens[1] == "s":
        tokens = tokens[2:]
    return tokens


def normalize_org(org: object, *, legal_suffixes: AbstractSet[str]) -> str:
    """Deterministic dedup key for an organization name.

    `jobs.org` is a denormalized free-text string written by a dozen different
    scrapers, so the same organization arrives spelled a dozen ways. This is
    the key for the hosted `organizations` table (docs/interview-prep-design.md
    §13), so it has to be stable and total: same org in, same key out.

    Rules, in order:
      0. Strip a job site's trailing "in US"/"in USA" display quirk.
      0b. Strip a trailing parenthetical that's exactly the initials of the
          preceding words ("Environmental Protection Agency (EPA)").
      1. Unicode NFKD + strip combining marks ("Fundación" → "fundacion").
      2. Lowercase.
      3. ``&`` → ``and`` ("Booz Allen & Hamilton" == "Booz Allen and Hamilton").
      4. All other punctuation → whitespace, whitespace collapsed.
      5. Drop a leading article ("The Urban Institute" → "urban institute").
      5b. Drop a leading "U.S." ("U.S. Environmental Protection Agency" →
          "environmental protection agency").
      6. Drop trailing legal suffixes, repeatedly ("Foo Co., Ltd." → "foo").

    *legal_suffixes* is the caller's lowercase token set for step 6 (e.g. ``{"inc", "llc", "ltd"}``).

    Steps 5, 5b, and 6 never empty the key: an org actually named
    "The Company" normalizes to "company", not "".
    """
    text = _IN_COUNTRY_SUFFIX_RE.sub("", str(org or ""))
    paren_match = _TRAILING_PAREN_RE.match(text)
    if paren_match:
        body, paren = paren_match.group(1), paren_match.group(2)
        paren_letters = re.sub(r"[^A-Za-z]", "", paren)
        if len(paren_letters) >= 2 and paren_letters.isupper():
            initials = "".join(tok[0] for tok in _org_tokens(body) if tok).upper()
            if initials == paren_letters:
                text = body

    tokens = _org_tokens(text)
    trimmed = list(tokens)
    while len(trimmed) > 1 and trimmed[-1] in legal_suffixes:
        trimmed.pop()
    return " ".join(trimmed or tokens)
