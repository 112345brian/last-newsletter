from dataclasses import replace
from datetime import UTC, date, datetime, time

import pytest

from last_newsletter_core.event_rules import (
    RejectReason,
    canonical_url,
    normalize_text,
    resolve_when,
    validate_candidate,
)
from last_newsletter_core.events import (
    AllDay,
    EntityRef,
    EntityRole,
    EventCandidate,
    EventDraft,
    EventKind,
    PartialWhen,
    Timed,
)

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_TZ = "America/New_York"


def test_weekday_pins_the_year() -> None:
    # "SATURDAY DEC 12": Dec 12 is a Saturday in 2026, not 2027.
    when = resolve_when(PartialWhen(month=12, day=12, weekday=5), now=_NOW, home_tz=_TZ)
    assert when == AllDay(date(2026, 12, 12))


def test_weekday_pins_next_year_across_the_boundary() -> None:
    now = datetime(2026, 12, 20, tzinfo=UTC)
    # Jan 9 is a Saturday in 2027.
    when = resolve_when(PartialWhen(month=1, day=9, weekday=5), now=now, home_tz=_TZ)
    assert when == AllDay(date(2027, 1, 9))


def test_no_weekday_takes_nearest_future_occurrence() -> None:
    now = datetime(2026, 12, 20, tzinfo=UTC)
    assert resolve_when(PartialWhen(month=1, day=5), now=now, home_tz=_TZ) == AllDay(
        date(2027, 1, 5)
    )


def test_weekday_that_fits_no_nearby_year_is_rejected() -> None:
    # Dec 12 is never a Monday in 2026 or 2027.
    assert (
        resolve_when(PartialWhen(month=12, day=12, weekday=0), now=_NOW, home_tz=_TZ)
        is RejectReason.AMBIGUOUS_YEAR
    )


def test_explicit_year_is_used_as_written() -> None:
    when = resolve_when(PartialWhen(year=2027, month=3, day=1), now=_NOW, home_tz=_TZ)
    assert when == AllDay(date(2027, 3, 1))


@pytest.mark.parametrize(
    "partial",
    [
        PartialWhen(month=2, day=30),
        PartialWhen(year=2026, month=13, day=1),
        PartialWhen(year=2027, month=2, day=29),
        PartialWhen(month=12, day=12, weekday=9),
    ],
)
def test_impossible_dates_are_rejected(partial: PartialWhen) -> None:
    assert resolve_when(partial, now=_NOW, home_tz=_TZ) in {
        RejectReason.INVALID_DATE,
        RejectReason.AMBIGUOUS_YEAR,
    }


def test_missing_month_or_day_is_missing_date() -> None:
    assert resolve_when(PartialWhen(month=12), now=_NOW, home_tz=_TZ) is RejectReason.MISSING_DATE
    assert resolve_when(PartialWhen(), now=_NOW, home_tz=_TZ) is RejectReason.MISSING_DATE


def test_time_makes_a_timed_value_in_the_given_zone() -> None:
    when = resolve_when(
        PartialWhen(year=2026, month=12, day=12, time=time(20, 0), tz="Europe/Paris"),
        now=_NOW,
        home_tz=_TZ,
    )
    assert isinstance(when, Timed)
    assert when.tz_name == "Europe/Paris"
    assert when.start == datetime(2026, 12, 12, 19, 0, tzinfo=UTC)


def test_unknown_zone_is_rejected() -> None:
    result = resolve_when(
        PartialWhen(year=2026, month=12, day=12, time=time(20, 0), tz="Nowhere/Land"),
        now=_NOW,
        home_tz=_TZ,
    )
    assert result is RejectReason.UNKNOWN_TIMEZONE


def test_past_dates_are_rejected_unless_recap() -> None:
    past = PartialWhen(year=2026, month=9, day=1)
    assert resolve_when(past, now=_NOW, home_tz=_TZ) is RejectReason.PAST_DATE
    assert resolve_when(past, now=_NOW, home_tz=_TZ, allow_past=True) == AllDay(date(2026, 9, 1))


def test_yesterday_is_inside_the_grace_period() -> None:
    assert resolve_when(PartialWhen(year=2026, month=11, day=5), now=_NOW, home_tz=_TZ) == AllDay(
        date(2026, 11, 5)
    )


def test_naive_now_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="timezone"):
        resolve_when(
            PartialWhen(month=12, day=12),
            now=datetime(2026, 11, 6, tzinfo=UTC).replace(tzinfo=None),
            home_tz=_TZ,
        )


def test_normalize_text_folds_case_accents_and_punctuation() -> None:
    assert normalize_text("  Café   DEL  Mar!! ") == "cafe del mar"
    assert normalize_text("\uff22\uff21\uff2e\uff24 \u2013 Live") == "band live"


def test_canonical_url_strips_tracking_and_noise() -> None:
    a = canonical_url("HTTPS://Example.com:443/events/42/?utm_source=x&b=2&a=1#top")
    b = canonical_url("https://example.com/events/42?a=1&b=2")
    assert a == b == "https://example.com/events/42?a=1&b=2"


@pytest.mark.parametrize("url", ["", "not a url", "javascript:alert(1)", "ftp://x.org/a"])
def test_canonical_url_rejects_non_http(url: str) -> None:
    assert canonical_url(url) is None


_BASE_CANDIDATE = EventCandidate(
    message_id="m1",
    title="Band at Venue",
    when=PartialWhen(year=2026, month=12, day=12),
    evidence="Band at Venue, Dec 12",
)


def _candidate(**overrides: object) -> EventCandidate:
    return replace(_BASE_CANDIDATE, **overrides)


def _validate(
    candidate: EventCandidate, *, body: str = "Come: Band at Venue, Dec 12!"
) -> EventDraft | RejectReason:
    return validate_candidate(
        candidate, message_body=body, now=_NOW, home_tz=_TZ, check_evidence=True
    )


def test_valid_candidate_becomes_a_draft() -> None:
    draft = _validate(
        _candidate(
            kind=None,
            entities=(
                EntityRef(name=" Venue ", role=EntityRole.VENUE),
                EntityRef(name="   ", role=EntityRole.HEADLINER),
            ),
            url="https://example.com/e/1?utm_medium=mail",
            uid="abc",
        )
    )
    assert not isinstance(draft, RejectReason)
    assert draft.kind is EventKind.EVENT
    assert draft.title == "Band at Venue"
    assert [e.name for e in draft.entities] == ["Venue"]
    assert draft.url == "https://example.com/e/1"
    assert draft.uid == "abc"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"title": None}, RejectReason.BLANK_TITLE),
        ({"title": "  "}, RejectReason.BLANK_TITLE),
        ({"title": "Ban\x00d"}, RejectReason.CONTROL_CHARACTERS),
        ({"summary": "x\x00"}, RejectReason.CONTROL_CHARACTERS),
        ({"title": "x" * 500}, RejectReason.TITLE_TOO_LONG),
        ({"when": None}, RejectReason.MISSING_DATE),
        ({"when": PartialWhen(year=2026)}, RejectReason.MISSING_DATE),
        ({"evidence": ""}, RejectReason.NO_EVIDENCE),
        ({"evidence": "never said this"}, RejectReason.EVIDENCE_NOT_IN_MESSAGE),
        (
            {"entities": (EntityRef(name="a\x00b", role=EntityRole.VENUE),)},
            RejectReason.CONTROL_CHARACTERS,
        ),
    ],
)
def test_bad_candidates_are_rejected_with_a_reason(
    overrides: dict[str, object], reason: RejectReason
) -> None:
    assert _validate(_candidate(**overrides)) is reason


def test_evidence_check_ignores_case_and_whitespace_and_can_be_skipped() -> None:
    assert not isinstance(_validate(_candidate(evidence="BAND   at venue,\nDec 12")), RejectReason)
    skipped = validate_candidate(
        _candidate(evidence="structured data"),
        message_body="",
        now=_NOW,
        home_tz=_TZ,
        check_evidence=False,
    )
    assert not isinstance(skipped, RejectReason)


def test_recap_candidates_may_be_in_the_past() -> None:
    past = PartialWhen(year=2026, month=9, day=1)
    assert _validate(_candidate(when=past)) is RejectReason.PAST_DATE
    assert not isinstance(_validate(_candidate(when=past, is_recap=True)), RejectReason)


def test_invalid_url_is_dropped_not_fatal() -> None:
    draft = _validate(_candidate(url="javascript:alert(1)"))
    assert not isinstance(draft, RejectReason)
    assert draft.url is None
