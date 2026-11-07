"""Resolve one source-reported date to an ISO calendar date, against the time it was observed.

Sources expose dates in incompatible forms: an ISO timestamp, or card text such as ``"Posted 2 days ago"``.
``resolve_date`` returns ``YYYY-MM-DD`` or ``""`` when the value is unusable. Dateparser is deliberately given an
explicit base (``observed_at``) so a relative value never drifts after it is stored.

Freshness: checked 2026-09-28; recheck by 2027-01-28. See freshness.json.
"""
from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import re
from datetime import date, datetime

_SOURCE_LABEL = re.compile(r"^(?:re)?posted\s+", re.IGNORECASE)
_RELATIVE_PLUS = re.compile(r"(?<=\d)\+(?=\s*(?:minute|hour|day|week|month))")
_JUST_POSTED = frozenset({"just posted", "new"})
_ISO_DATE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")


def first_iso_date(text: str) -> date | None:
    """The first ``YYYY-MM-DD`` calendar date in ``text``, or None.

    For reading a date out of a free-text reply (an LLM told to answer with only a date still
    sometimes explains itself). A well-formed but impossible date (``2026-13-45``) is None, not an
    error, so a caller never needs its own try/except around it.
    """
    for match in _ISO_DATE.finditer(text or ""):
        try:
            return date.fromisoformat(match.group(0))
        except ValueError:
            continue
    return None


def _parseable_source_value(raw: str) -> str:
    """Remove UI labels without implementing a date parser ourselves."""
    value = _SOURCE_LABEL.sub("", raw.strip())
    value = _RELATIVE_PLUS.sub("", value)
    return "now" if value.casefold() in _JUST_POSTED else value


def resolve_date(
    value: object,
    *,
    observed_at: datetime,
    languages: tuple[str, ...] = ("en",),
) -> str:
    """Return an ISO calendar date for one source value, or ``""`` if unusable.

    ``languages`` is explicit because source-card text is not arbitrary prose;
    callers should add a source's known language rather than enable language
    guessing. The default covers the currently supported English-language
    boards.
    """
    raw = value.strip() if isinstance(value, str) else ""
    if not raw:
        return ""
    # Imported here: dateparser costs ~0.16s to import and most CLI commands never parse a date.
    from dateparser import parse

    reference = observed_at
    if reference.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    parsed = parse(
        _parseable_source_value(raw),
        languages=list(languages),
        settings={
            "PREFER_DATES_FROM": "past",
            "RELATIVE_BASE": reference,
            "RETURN_AS_TIMEZONE_AWARE": True,
        },
    )
    return parsed.date().isoformat() if parsed is not None else ""
