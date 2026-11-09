"""Scored same-event / different-event pairs for the identity ladder.

Each case is one already-known event and one incoming listing, labelled by what a person would say:
MERGE (same happening, so the listing must be cited as a mention) or SEPARATE (different happenings,
so it must stay its own event). The shapes are the ones two honest senders produce for one show: a
longer or shorter title, a missing venue, a different showtime list, a late-night date. Malformed
listings are out of scope: a source that gets the date, title or venue wrong cannot be repaired
here, and the ladder fails that way by keeping events separate.

Three things are asserted:
1. every case individually, so a failure names the pair;
2. no wrong merge anywhere (a wrong merge hides an event; a missed one only repeats it);
3. recall over the MERGE cases, so loosening a rule cannot quietly cost duplicates.

`KNOWN_SPLITS` are real duplicates the ladder deliberately does not merge. They are pinned as
SEPARATE so that a change of behaviour is a visible decision rather than a surprise.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as clock
from uuid import UUID

import pytest

from last_newsletter_core.event_identity import identify
from last_newsletter_core.events import (
    AllDay,
    EntityRef,
    EntityRole,
    Event,
    EventDraft,
    EventId,
    EventKind,
    MatchRule,
    Mention,
)

_SEEN = datetime(2026, 11, 6, tzinfo=UTC)
FRI, SAT, SUN = date(2026, 11, 13), date(2026, 11, 14), date(2026, 11, 15)
_NOON, _4PM, _8PM, _9PM = clock(12), clock(16), clock(20), clock(21)


@dataclass(frozen=True)
class Listing:
    title: str
    day: date
    venue: str = ""
    times: tuple[clock, ...] = ()
    uid: str | None = None
    url: str | None = None
    night_of: date | None = None


@dataclass(frozen=True)
class Pair:
    name: str
    known: Listing
    incoming: Listing
    same: bool


def _venue(name: str) -> tuple[EntityRef, ...]:
    return (EntityRef(name=name, role=EntityRole.VENUE),) if name else ()


def _event(n: int, item: Listing) -> Event:
    event_id = EventId(UUID(int=n))
    return Event(
        id=event_id,
        kind=EventKind.EVENT,
        title=item.title,
        summary="",
        when=AllDay(item.day),
        entities=_venue(item.venue),
        mentions=(
            Mention(
                message_id=f"m{n}",
                seen_at=_SEEN,
                source="s",
                evidence="e",
                match_rule=MatchRule.NEW,
                cited_event_id=event_id,
            ),
        ),
        first_seen=_SEEN,
        last_seen=_SEEN,
        uid=item.uid,
        url=item.url,
        night_of=item.night_of,
        showtimes=item.times,
    )


def _draft(item: Listing) -> EventDraft:
    return EventDraft(
        kind=EventKind.EVENT,
        title=item.title,
        summary="",
        when=AllDay(item.day),
        evidence="e",
        entities=_venue(item.venue),
        uid=item.uid,
        url=item.url,
        night_of=item.night_of,
        showtimes=item.times,
    )


def _merged(pair: Pair) -> bool:
    return identify(_draft(pair.incoming), [_event(1, pair.known)]).event is not None


FILM = Listing("La Bola Negra", SAT, "", (_NOON, _4PM))

MERGE = (
    Pair(
        "identical title, venue and date",
        Listing("Mdou Moctar", FRI, "The Fonda"),
        Listing("Mdou Moctar", FRI, "The Fonda"),
        same=True,
    ),
    Pair(
        "case, accents and punctuation differ",
        Listing("Café du Nord", FRI, "Café du Nord"),
        Listing("CAFE DU NORD!", FRI, "cafe du nord"),
        same=True,
    ),
    Pair(
        "same title and venue, no showtimes on either side",
        Listing("Open Mic Night", SUN, "Hotel Cafe"),
        Listing("Open Mic Night", SUN, "Hotel Cafe"),
        same=True,
    ),
    Pair(
        "promoter adds the venue to the title, same showtimes",
        FILM,
        Listing(
            "La Bola Negra screening at The Frida Cinema", SAT, "The Frida Cinema", (_NOON, _4PM)
        ),
        same=True,
    ),
    Pair(
        "venue missing on the known side, titles related, one showtime shared",
        Listing("Jazz Quartet", FRI, "", (_8PM,)),
        Listing("Jazz Quartet Live at Blue Whale", FRI, "Blue Whale", (_8PM, _9PM)),
        same=True,
    ),
    Pair(
        "shorter title in the second email, overlapping showtime lists",
        Listing(
            "La Bola Negra screening at The Frida Cinema", SAT, "The Frida Cinema", (_NOON, _4PM)
        ),
        Listing("la bola negra", SAT, "", (_4PM, _8PM)),
        same=True,
    ),
    Pair(
        "one-letter typo in the title, same showtimes",
        Listing("La Bola Negra", SAT, "", (_4PM,)),
        Listing("La Bola Negrra", SAT, "", (_4PM,)),
        same=True,
    ),
    Pair(
        "after-midnight listing is the night before",
        Listing("Late Set", FRI, "The Echo", (), None, None, None),
        Listing("Late Set", SAT, "The Echo", (), None, None, FRI),
        same=True,
    ),
    Pair(
        "calendar UID matches although the title was renamed",
        Listing("Spring Gala", SAT, "City Hall", uid="uid-1"),
        Listing("Spring Gala (moved indoors)", SAT, "City Hall", uid="uid-1"),
        same=True,
    ),
    Pair(
        "same ticket URL, title reworded",
        Listing("Dub Club", FRI, "Zebulon", url="https://tix.example.com/e/4412"),
        Listing("Dub Club with guests", FRI, "Zebulon", url="https://tix.example.com/e/4412"),
        same=True,
    ),
)

SEPARATE = (
    Pair(
        "same title and venue on consecutive days are two events",
        Listing("Mdou Moctar", FRI, "The Fonda"),
        Listing("Mdou Moctar", SAT, "The Fonda"),
        same=False,
    ),
    Pair(
        "same title, same day, different venues",
        Listing("Open Mic Night", SUN, "Hotel Cafe"),
        Listing("Open Mic Night", SUN, "The Satellite"),
        same=False,
    ),
    Pair(
        "related titles on one day but no shared showtime",
        Listing("La Bola Negra", SAT, "", (_NOON,)),
        Listing("La Bola Negra screening at The Frida Cinema", SAT, "The Frida Cinema", (_9PM,)),
        same=False,
    ),
    Pair(
        "related titles and times but the venues conflict",
        Listing("Jazz Quartet", FRI, "Blue Whale", (_8PM,)),
        Listing("Jazz Quartet", FRI, "The Mint", (_8PM,)),
        same=False,
    ),
    Pair(
        "related titles on one day, no times given on either side",
        Listing("Jazz Quartet", FRI, ""),
        Listing("Jazz Quartet Live at Blue Whale", FRI, "Blue Whale"),
        same=False,
    ),
    Pair(
        "a title too short to trust is not enough to relate two listings",
        Listing("DJ", FRI, "", (_9PM,)),
        Listing("DJ Shadow", FRI, "", (_9PM,)),
        same=False,
    ),
    Pair(
        "one title only appears inside a word of the other",
        Listing("Rave", FRI, "", (_9PM,)),
        Listing("Brave Heart", FRI, "", (_9PM,)),
        same=False,
    ),
    Pair(
        "unrelated titles, same venue, same night",
        Listing("Mdou Moctar", FRI, "The Fonda", (_8PM,)),
        Listing("Open Mic Night", FRI, "The Fonda", (_8PM,)),
        same=False,
    ),
    Pair(
        "contained title but a different date",
        Listing("La Bola Negra", SAT, "", (_4PM,)),
        Listing("La Bola Negra screening at The Frida Cinema", SUN, "The Frida Cinema", (_4PM,)),
        same=False,
    ),
    Pair(
        "a UID that differs is not evidence of sameness",
        Listing("Spring Gala", SAT, "City Hall", uid="uid-1"),
        Listing("Autumn Gala", SUN, "City Hall", uid="uid-2"),
        same=False,
    ),
)

# Real duplicates that stay split on purpose. Merging them would need a looser rule than the
# ladder allows without also merging unrelated same-night shows.
KNOWN_SPLITS = (
    Pair(
        "reordered title words with no showtimes",
        Listing("Jazz Night", FRI, "Blue Whale"),
        Listing("Night of Jazz", FRI, "Blue Whale"),
        same=False,
    ),
    Pair(
        "venue spelled differently and the title reworded",
        Listing("Dub Club", FRI, "Zebulon", (_9PM,)),
        Listing("Dub Club presents: Roots Night", FRI, "Zebulon Cafe Concert", (_9PM,)),
        same=False,
    ),
)

ALL = (*MERGE, *SEPARATE, *KNOWN_SPLITS)


@pytest.mark.parametrize("pair", ALL, ids=[p.name for p in ALL])
def test_pair_gets_the_label_a_person_would_give(pair: Pair) -> None:
    assert _merged(pair) is pair.same


def test_the_ladder_never_merges_two_different_events() -> None:
    wrong = [p.name for p in (*SEPARATE, *KNOWN_SPLITS) if _merged(p) and not p.same]
    assert wrong == []


def test_the_ladder_finds_every_labelled_duplicate() -> None:
    labelled = [p for p in ALL if p.same]
    found = [p for p in labelled if _merged(p)]
    assert len(found) / len(labelled) == 1.0


def test_known_splits_are_documented_as_separate() -> None:
    assert all(not p.same for p in KNOWN_SPLITS)
    assert len(KNOWN_SPLITS) >= 1
