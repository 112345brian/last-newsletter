from __future__ import annotations

import pytest

from last_newsletter_adapter_events.prefilter import has_date_signal
from last_newsletter_adapter_events.when import parse_when, split_listing


@pytest.mark.parametrize(
    "text", ["Dec 12", "12 December", "12/12", "2026-12-12", "Saturday", "9pm", "tonight"]
)
def test_signal_yes(text: str) -> None:
    assert has_date_signal("", text)


@pytest.mark.parametrize("text", ["", "Your order has shipped", "20% off everything, shop now"])
def test_signal_no(text: str) -> None:
    assert not has_date_signal("", text)


def test_when_variants() -> None:
    w = parse_when("Fri 12/11 8:30 PM")
    assert (w.month, w.day, w.weekday, w.year) == (12, 11, 4, None)
    assert w.time is not None
    assert (w.time.hour, w.time.minute) == (20, 30)
    w = parse_when("2026-12-12")
    assert (w.year, w.month, w.day) == (2026, 12, 12)
    w = parse_when("12 Dec")
    assert (w.month, w.day) == (12, 12)
    w = parse_when("12am")
    assert w.time is not None
    assert w.time.hour == 0


@pytest.mark.parametrize("text", ["", "soon", "Dec 45", "13/40", "Sunset 5"])
def test_when_garbage_stays_partial(text: str) -> None:
    w = parse_when(text)
    assert w.day is None or 1 <= w.day <= 31
    assert w.year is None


def test_a_list_of_showtimes_is_not_a_time_range() -> None:
    w = parse_when("Friday, November 13th - 12PM, 3:30PM, 7PM")
    assert (w.month, w.day, w.weekday) == (11, 13, 4)
    assert w.time is not None
    assert (w.time.hour, w.time.minute) == (12, 0)
    assert w.end_time is None
    assert [(t.hour, t.minute) for t in w.showtimes] == [(12, 0), (15, 30), (19, 0)]


@pytest.mark.parametrize(
    "text", ["Saturday 1:30am-5am", "Sat Dec 12, 9pm to 2am", "Sat 9pm \u2013 2am"]
)
def test_a_dashed_or_worded_range_still_has_an_end_time(text: str) -> None:
    w = parse_when(text)
    assert w.end_time is not None
    assert len(w.showtimes) <= 1


def test_one_listing_with_several_days_splits_into_one_segment_per_date() -> None:
    text = (
        "Friday, November 13th - 12PM, 3:30PM, 7PM Saturday, November 14th - 12PM, 3:30PM "
        "Sunday, November 15th - 10AM"
    )
    parts = split_listing(text)
    assert len(parts) == 3
    days = [(p.month, p.day, p.weekday) for p in map(parse_when, parts)]
    assert days == [(11, 13, 4), (11, 14, 5), (11, 15, 6)]
    assert [len(parse_when(p).showtimes) for p in parts] == [3, 2, 0]


@pytest.mark.parametrize(
    "text", ["Sat Dec 12, 9pm", "Friday, November 13th - 12PM, 3:30PM", "Sat 9pm, Sun 8pm", ""]
)
def test_a_single_date_is_not_split(text: str) -> None:
    assert split_listing(text) == [text]
