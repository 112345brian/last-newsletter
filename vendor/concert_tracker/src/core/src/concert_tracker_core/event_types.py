"""What kind of event something is: a concert, a rave, a festival, a comedy night, and so on.

An `EventTypeRules` is an ordered list of rules, each saying "an event that looks like *this* is
a *that*". The first rule that matches wins; an event no rule matches is `EventType.UNKNOWN`, which
is an answer of its own and never defaults to some type. Callers that filter by type say how many
events that hid.

The rules are plain data (a packaged seed plus the owner's own file, laid over it with
`with_overrides`); nothing here reads a file or checks a particular title. A rule names a `type`
and one or more conditions; every kind of condition it names must hold, and within one kind any
listed value is enough:

- `title_phrases`: the title contains the phrase as whole words ("stand-up", "b2b").
- `sources`: one of the sources that listed the event (`mycalendar`).
- `venues`: the venue is one of these names (compared like the venue directory does).
- `venue_categories`: the venue has at least one of these categories.
- `venue_categories_only`: the venue has categories and every one of them is listed.
- `promoter_affinities`: an organizer the promoter directory knows is known for this scene.
- `genres`: one of the artists' genres, when genres were looked up.
- `tags`: one of the tags the source gave the event.

`parse_event_type_rules` reads `{"rules": [{"type": ..., <conditions>}, ...]}` and raises
`EventTypeRulesError` naming the rule at fault.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from dataclasses import dataclass, fields
from enum import StrEnum
from typing import TYPE_CHECKING, TypeVar

from concert_tracker_core.event_rules import normalize_text, normalize_without_leading_article
from concert_tracker_core.promoters import Affinity
from concert_tracker_core.source_runs import source_key
from concert_tracker_core.venue_categories import VenueCategory

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

_M = TypeVar("_M", bound=StrEnum)


class EventType(StrEnum):
    CONCERT = "concert"  # live bands and artists on a stage
    RAVE = "rave"  # a club night, rave or other electronic-scene event
    FESTIVAL = "festival"
    COMEDY = "comedy"
    FILM = "film"
    THEATER = "theater"
    OTHER = "other"  # known to be none of the above (a workshop, a market, an exhibit)
    UNKNOWN = "unknown"  # no rule could tell: an answer, never a guess


class EventTypeRulesError(ValueError):
    """The event type rules are malformed: names the rule and what is wrong."""


@dataclass(frozen=True, slots=True)
class EventFacts:
    """Everything a rule may look at about one event; every field may be empty."""

    title: str
    venue: str = ""
    venue_categories: frozenset[VenueCategory] = frozenset()
    sources: tuple[str, ...] = ()
    promoter_affinities: frozenset[Affinity] = frozenset()
    genres: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


def _word(text: str) -> str:
    return text.strip().casefold()


def _normalized(values: frozenset[str], how: Callable[[str], str]) -> frozenset[str]:
    return frozenset(how(value) for value in values)


@dataclass(frozen=True, slots=True)
class EventTypeRule:
    """One rule: events matching every condition it names are of `type`.

    Values are normalized when the rule is built, so rules written by hand and rules read from a
    file compare the same way.
    """

    type: EventType
    title_phrases: frozenset[str] = frozenset()
    sources: frozenset[str] = frozenset()
    venues: frozenset[str] = frozenset()
    venue_categories: frozenset[VenueCategory] = frozenset()
    venue_categories_only: frozenset[VenueCategory] = frozenset()
    promoter_affinities: frozenset[Affinity] = frozenset()
    genres: frozenset[str] = frozenset()
    tags: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        normalized = {
            "title_phrases": _normalized(self.title_phrases, normalize_text),
            "sources": _normalized(self.sources, source_key),
            "venues": _normalized(self.venues, normalize_without_leading_article),
            "genres": _normalized(self.genres, _word),
            "tags": _normalized(self.tags, _word),
        }
        for name, values in normalized.items():
            object.__setattr__(self, name, values)
        if not any(getattr(self, f.name) for f in fields(self) if f.name != "type"):
            msg = f"a {self.type.value} rule must name at least one condition"
            raise EventTypeRulesError(msg)
        if any("" in values for values in normalized.values()):
            msg = f"a {self.type.value} rule has a blank value"
            raise EventTypeRulesError(msg)

    def matches(self, facts: EventFacts) -> bool:
        words = f" {normalize_text(facts.title)} "
        checks = (
            not self.title_phrases or any(f" {p} " in words for p in self.title_phrases),
            not self.sources or any(source_key(s) in self.sources for s in facts.sources),
            not self.venues or normalize_without_leading_article(facts.venue) in self.venues,
            not self.venue_categories
            or not self.venue_categories.isdisjoint(facts.venue_categories),
            not self.venue_categories_only
            or (
                bool(facts.venue_categories)
                and facts.venue_categories <= self.venue_categories_only
            ),
            not self.promoter_affinities
            or not self.promoter_affinities.isdisjoint(facts.promoter_affinities),
            not self.genres or any(_word(g) in self.genres for g in facts.genres),
            not self.tags or any(_word(t) in self.tags for t in facts.tags),
        )
        return all(checks)


@dataclass(frozen=True, slots=True)
class EventTypeRules:
    """Rules in priority order: the first that matches an event decides its type."""

    rules: tuple[EventTypeRule, ...] = ()

    def classify(self, facts: EventFacts) -> EventType:
        """The type of the first matching rule; `UNKNOWN` when none matches."""
        for rule in self.rules:
            if rule.matches(facts):
                return rule.type
        return EventType.UNKNOWN

    def with_overrides(self, other: EventTypeRules) -> EventTypeRules:
        """A new set where `other`'s rules are tried before these; neither input changes."""
        return EventTypeRules((*other.rules, *self.rules))


def _strings(raw: dict[str, object], key: str, where: str) -> frozenset[str]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        msg = f"{where}: {key} must be a list of strings"
        raise EventTypeRulesError(msg)
    return frozenset(item for item in value if isinstance(item, str))


def _members(kind: type[_M], raw: Iterable[str], where: str, key: str) -> frozenset[_M]:
    found: set[_M] = set()
    for item in raw:
        try:
            found.add(kind(item))
        except ValueError:
            valid = ", ".join(member.value for member in kind)
            msg = f"{where}: {key} has unknown value {item!r} (one of: {valid})"
            raise EventTypeRulesError(msg) from None
    return frozenset(found)


def _rule(raw: object, where: str) -> EventTypeRule:
    if not isinstance(raw, dict):
        msg = f"{where} must be an object"
        raise EventTypeRulesError(msg)
    extra = sorted(set(raw) - {f.name for f in fields(EventTypeRule)})
    if extra:
        msg = f"{where}: unknown key(s) {', '.join(map(repr, extra))}"
        raise EventTypeRulesError(msg)
    kind = raw.get("type")
    if not isinstance(kind, str):
        msg = f"{where}: type must be text"
        raise EventTypeRulesError(msg)
    (event_type,) = _members(EventType, [kind], where, "type")
    return EventTypeRule(
        type=event_type,
        title_phrases=_strings(raw, "title_phrases", where),
        sources=_strings(raw, "sources", where),
        venues=_strings(raw, "venues", where),
        venue_categories=_members(
            VenueCategory, _strings(raw, "venue_categories", where), where, "venue_categories"
        ),
        venue_categories_only=_members(
            VenueCategory,
            _strings(raw, "venue_categories_only", where),
            where,
            "venue_categories_only",
        ),
        promoter_affinities=_members(
            Affinity, _strings(raw, "promoter_affinities", where), where, "promoter_affinities"
        ),
        genres=_strings(raw, "genres", where),
        tags=_strings(raw, "tags", where),
    )


def parse_event_type_rules(data: object) -> EventTypeRules:
    """Build rules from parsed JSON: `{"rules": [{"type": "rave", "sources": ["djs"]}, ...]}`."""
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        msg = 'event type rules must be an object with a "rules" list'
        raise EventTypeRulesError(msg)
    return EventTypeRules(
        tuple(_rule(raw, f"rule #{position}") for position, raw in enumerate(data["rules"], 1))
    )
