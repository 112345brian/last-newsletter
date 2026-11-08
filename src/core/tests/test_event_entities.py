from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from last_newsletter_core.events import (
    AllDay,
    Event,
    EventId,
    EventKind,
    ItemState,
    MatchRule,
    Mention,
    Timed,
)

_T = datetime(2026, 12, 12, 20, 0, tzinfo=UTC)
_ID = EventId(UUID(int=1))


_BASE_MENTION = Mention(
    message_id="m1",
    seen_at=_T,
    source="promoter",
    evidence="SATURDAY DEC 12",
    match_rule=MatchRule.NEW,
    cited_event_id=_ID,
)


def _mention(**overrides: object) -> Mention:
    return replace(_BASE_MENTION, **overrides)


_BASE_EVENT = Event(
    id=_ID,
    kind=EventKind.EVENT,
    title="Band at Venue",
    summary="",
    when=AllDay(date(2026, 12, 12)),
    mentions=(_BASE_MENTION,),
    first_seen=_T,
    last_seen=_T,
)


def _event(**overrides: object) -> Event:
    return replace(_BASE_EVENT, **overrides)


def test_event_defaults_are_open_with_no_duplicates() -> None:
    event = _event()
    assert event.state is ItemState.OPEN
    assert event.possible_duplicates == ()
    assert event.entities == ()


def test_naive_datetimes_are_rejected_everywhere() -> None:
    naive = datetime(2026, 12, 12, 20, 0, tzinfo=UTC).replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone"):
        _mention(seen_at=naive)
    with pytest.raises(ValueError, match="timezone"):
        _event(first_seen=naive)
    with pytest.raises(ValueError, match="timezone"):
        _event(last_seen=naive)
    with pytest.raises(ValueError, match="timezone"):
        Timed(start=naive, tz_name="UTC")
    with pytest.raises(ValueError, match="timezone"):
        Timed(start=_T, tz_name="UTC", end=naive)


@pytest.mark.parametrize("title", ["", "   ", "\n"])
def test_blank_title_is_rejected(title: str) -> None:
    with pytest.raises(ValueError, match="title"):
        _event(title=title)


def test_nul_character_in_title_is_rejected() -> None:
    with pytest.raises(ValueError, match="control"):
        _event(title="Band\x00 at Venue")


def test_timed_rejects_unknown_zone_and_backwards_range() -> None:
    with pytest.raises(ValueError, match="time zone"):
        Timed(start=_T, tz_name="Mars/Olympus")
    with pytest.raises(ValueError, match="end"):
        Timed(start=_T, tz_name="UTC", end=_T - timedelta(hours=1))


def test_event_needs_a_mention_and_ordered_seen_times() -> None:
    with pytest.raises(ValueError, match="mention"):
        _event(mentions=())
    with pytest.raises(ValueError, match="last_seen"):
        _event(last_seen=_T - timedelta(days=1))


def test_event_cannot_list_itself_as_possible_duplicate() -> None:
    with pytest.raises(ValueError, match="itself"):
        _event(possible_duplicates=(_ID,))
