"""Read who is playing out of an event title: promoter, headliners, supports, event name.

Venues and ticketing sites put the whole bill in one string ("KCRW Presents: Moon Panda",
"Saosin w/ Silent Planet (18+)", "Hippie Death Cult / Monarch"). `parse_title` recognises the
common shapes and says which one fired. It is a pure function: no clock, network or ledger.

It never invents a name. Every string it returns is a stripped, literal piece of the title, and
when no pattern fires nothing is recognised (`pattern` is NONE and no promoter, headliner,
support or event name is set). A recognised pattern is still a *reading*, not a fact: a title
like "Making Love with David Magidoff" parses as a band "Making Love" with a guest, because
nothing in the text says otherwise. Callers decide how far to trust it; `pattern` is there for
that. The titles come from untrusted sources, so control characters and over-long titles are
treated as unrecognisable.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

import re
from dataclasses import dataclass
from enum import StrEnum

from concert_tracker_core.event_rules import MAX_TITLE_LENGTH
from concert_tracker_core.events import has_control_characters


class TitlePattern(StrEnum):
    """Which shape of title was recognised (also the audit trail for a parse)."""

    NONE = "none"
    PROMOTER_PRESENTS = "promoter_presents"  # "<promoter> presents: <bill>"
    EVENING_WITH = "evening_with"  # "An Evening with <artist>"
    WITH_SUPPORT = "with_support"  # "<artist> with|w/ <support>, <support> & <support>"
    ARTIST_TOUR = "artist_tour"  # "<artist>: <tour name>" (or " - ")
    SLASH_BILL = "slash_bill"  # "<artist> / <support> / <support>"
    COMMA_BILL = "comma_bill"  # "<artist>, <support>, <support>" (three or more)
    X_BILL = "x_bill"  # "<artist> x <artist>" (a co-headlined bill)


@dataclass(frozen=True, slots=True)
class ParsedTitle:
    """What a title says. Every string is a literal, stripped piece of the original title."""

    pattern: TitlePattern
    promoter: str | None = None
    headliners: tuple[str, ...] = ()
    supports: tuple[str, ...] = ()
    event_name: str | None = None
    decorations: tuple[str, ...] = ()
    """Listing noise split off the title: "(21+)", "- Night 2", "SOLD OUT", "Early Show"."""
    leftover: str | None = None
    """The title minus decorations, set only when no pattern fired."""

    @property
    def recognised(self) -> bool:
        return self.pattern is not TitlePattern.NONE


@dataclass(frozen=True, slots=True)
class _Body:
    pattern: TitlePattern
    headliners: tuple[str, ...] = ()
    supports: tuple[str, ...] = ()
    event_name: str | None = None


_DASHES = "\\-\u2013\u2014"  # hyphen, en dash, em dash, as regex character-class content
_DECORATION_WORDS = (
    r"(?:ages?\s*\d{2}\+|\d{2}\+|all\s+ages|night\s*\d+|sold\s+out|(?:early|late)\s+show)"
)
_DECORATED = rf"(?P<dec>[(\[]\s*{_DECORATION_WORDS}\s*[)\]]|{_DECORATION_WORDS})"
_TRAILING_DECORATION = re.compile(rf"(?:\s*[{_DASHES}|,:]\s*|\s+){_DECORATED}\s*$", re.IGNORECASE)
_LEADING_DECORATION = re.compile(rf"^{_DECORATED}\s*(?:[{_DASHES}|:]\s*|\s+)", re.IGNORECASE)

_PRESENTS = re.compile(
    rf"^(?P<promoter>.+?)\s+presents?\s*[:{_DASHES}]\s*(?P<rest>\S.*)$", re.IGNORECASE | re.DOTALL
)
_EVENING_WITH = re.compile(r"^an\s+evening\s+with\s+(?P<rest>\S.*)$", re.IGNORECASE | re.DOTALL)
_WITH_PARENTHESIS = re.compile(
    r"^(?P<left>.*?)\s*\(\s*(?:with|w/)\s+(?P<right>[^()]*?)\s*\)$", re.IGNORECASE | re.DOTALL
)
_WITH = re.compile(r"^(?P<left>.*?\S)\s+(?:with|w/)\s+(?P<right>\S.*)$", re.IGNORECASE | re.DOTALL)
_TOUR_WORDS = re.compile(
    r"\b(?:tour|anniversary|(?:album\s+|record\s+)?release\s+show"
    r"|record\s+release|album\s+release)\b",
    re.IGNORECASE,
)
_HOSTED_WORDS = re.compile(
    r"\b(?:nights?|karaoke|hike|workshop|brunch|class|evening|celebration|party|festival|series)\b",
    re.IGNORECASE,
)
_TITLE_SEPARATOR = re.compile(rf"\s+[{_DASHES}]\s+|:\s+")
_SUPPORT_SPLIT = re.compile(
    r"\s*,\s*|\s+\+\s+|\s+/\s+|\s+&\s+|\s+and\s+(?=special\s+guests?\b)", re.IGNORECASE
)
_SPECIAL_GUESTS = re.compile(r"^(?:and\s+)?special\s+guests?\b\s*", re.IGNORECASE)
_NOISE_ITEM = re.compile(
    r"^(?:guests?|more|and\s+more|friends|and\s+friends|others)$", re.IGNORECASE
)
_AND_FRIENDS = re.compile(r"\s+and\s+friends$", re.IGNORECASE)
_PLUS_MORE = re.compile(r"\s*\+\s*more\s*$", re.IGNORECASE)
_SLASH_SPLIT = re.compile(r"\s+/\s+")
_MIN_COMMA_BILL = 3
_MIN_BILL = 2


def parse_title(title: str) -> ParsedTitle:
    """Recognise a promoter, headliners, supports and event name in `title`, if a pattern fits."""
    if not title.strip() or len(title) > MAX_TITLE_LENGTH or has_control_characters(title):
        return ParsedTitle(TitlePattern.NONE)
    base, decorations = _split_decorations(title.strip())
    if not base:
        return ParsedTitle(TitlePattern.NONE, decorations=decorations)
    found = _parse_presents(base) or _parse_evening_with(base)
    if found is None:
        body = _parse_body(base)
        found = (None, body) if body is not None else None
    if found is None:
        return ParsedTitle(TitlePattern.NONE, decorations=decorations, leftover=base)
    promoter, body = found
    return ParsedTitle(
        body.pattern,
        promoter=promoter,
        headliners=body.headliners,
        supports=body.supports,
        event_name=body.event_name,
        decorations=decorations,
    )


def _split_decorations(text: str) -> tuple[str, tuple[str, ...]]:
    found: list[str] = []
    while True:
        for pattern, cut in ((_TRAILING_DECORATION, True), (_LEADING_DECORATION, False)):
            match = pattern.search(text)
            if match is None:
                continue
            found.append(match.group("dec"))
            text = text[: match.start()] if cut else text[match.end() :]
            text = text.strip()
            break
        else:
            return text, tuple(found)


def _parse_presents(text: str) -> tuple[str | None, _Body] | None:
    match = _PRESENTS.match(text)
    if match is None:
        return None
    promoter, rest = str(match.group("promoter")).strip(), str(match.group("rest")).strip()
    if not promoter or not rest:
        return None
    body = _parse_body(rest)
    if body is not None:
        return promoter, _Body(
            TitlePattern.PROMOTER_PRESENTS, body.headliners, body.supports, body.event_name
        )
    if _TOUR_WORDS.search(rest):
        return promoter, _Body(TitlePattern.PROMOTER_PRESENTS, event_name=rest)
    return promoter, _Body(TitlePattern.PROMOTER_PRESENTS, headliners=(rest,))


def _parse_evening_with(text: str) -> tuple[None, _Body] | None:
    match = _EVENING_WITH.match(text)
    if match is None:
        return None
    return None, _Body(TitlePattern.EVENING_WITH, headliners=(str(match.group("rest")).strip(),))


def _parse_body(text: str) -> _Body | None:
    for parser in (_with_support, _artist_tour, _slash_bill, _x_bill, _comma_bill):
        body = parser(text)
        if body is not None:
            return body
    return None


def _is_plain_name(text: str) -> bool:
    """False for a part that is itself a "Series: thing" or "A - B" title, not a single name."""
    return bool(text) and ": " not in text and " - " not in text and not _SLASH_SPLIT.search(text)


def _mostly_upper(text: str) -> bool:
    return sum(c.isupper() for c in text) > sum(c.islower() for c in text)


def _co_headliners(text: str) -> tuple[str, ...]:
    """`A x B` is a co-headlined bill; an upper-case `X` only counts in an upper-case title."""
    splitter = re.compile(r"\s+x\s+", re.IGNORECASE if _mostly_upper(text) else 0)
    parts = tuple(str(part).strip() for part in splitter.split(text))
    if len(parts) >= _MIN_BILL and all(_is_plain_name(part) for part in parts):
        return parts
    return (text.strip(),)


def _support_items(text: str) -> tuple[str, ...]:
    items: list[str] = []
    for raw in _SUPPORT_SPLIT.split(text):
        item = _AND_FRIENDS.sub("", _SPECIAL_GUESTS.sub("", raw.strip())).strip()
        if item and not _NOISE_ITEM.match(item):
            items.append(item)
    return tuple(items)


def _with_support(text: str) -> _Body | None:
    parenthesised = _WITH_PARENTHESIS.match(text)
    match = parenthesised or _WITH.match(text)
    if match is None:
        return None
    left, right = str(match.group("left")).strip(), str(match.group("right")).strip()
    if not _is_plain_name(left):
        return None
    guests = _support_items(right)
    if _TOUR_WORDS.search(left):
        return _Body(TitlePattern.WITH_SUPPORT, supports=guests, event_name=left)
    if _HOSTED_WORDS.search(left):
        return _Body(TitlePattern.WITH_SUPPORT, headliners=guests, event_name=left)
    return _Body(TitlePattern.WITH_SUPPORT, headliners=_co_headliners(left), supports=guests)


def _artist_tour(text: str) -> _Body | None:
    for separator in _TITLE_SEPARATOR.finditer(text):
        left, right = text[: separator.start()].strip(), text[separator.end() :].strip()
        if left and right and _TOUR_WORDS.search(right) and not _SLASH_SPLIT.search(left):
            return _Body(
                TitlePattern.ARTIST_TOUR, headliners=_co_headliners(left), event_name=right
            )
    return None


def _slash_bill(text: str) -> _Body | None:
    parts = tuple(str(part).strip() for part in _SLASH_SPLIT.split(text))
    if len(parts) < _MIN_BILL or not all(_is_plain_name(part) for part in parts):
        return None
    return _Body(TitlePattern.SLASH_BILL, headliners=parts[:1], supports=parts[1:])


def _x_bill(text: str) -> _Body | None:
    names = _co_headliners(text)
    if len(names) < _MIN_BILL:
        return None
    return _Body(TitlePattern.X_BILL, headliners=names)


def _comma_bill(text: str) -> _Body | None:
    parts = tuple(part.strip() for part in _PLUS_MORE.sub("", text).split(","))
    if len(parts) < _MIN_COMMA_BILL or not all(_is_plain_name(part) for part in parts):
        return None
    return _Body(TitlePattern.COMMA_BILL, headliners=parts[:1], supports=parts[1:])
