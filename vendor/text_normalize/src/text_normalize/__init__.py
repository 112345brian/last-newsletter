"""Normalize free text and organisation names into stable comparison keys.

Install::

    text_normalize @ git+https://github.com/112345brian/bripe-job-search.git@<sha>#subdirectory=libs/text_normalize

``normalize(text, kind)`` for the text kinds and ``normalize_org(name, legal_suffixes=...)`` for employer names; the
legal-suffix vocabulary is the caller's, so the lib carries no data of its own.
"""

__arbor__ = {"ring": "core"}

from text_normalize.keys import NormalizeKind, normalize, normalize_org

__all__ = ["NormalizeKind", "normalize", "normalize_org"]
