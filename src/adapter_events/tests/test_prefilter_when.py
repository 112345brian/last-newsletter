from __future__ import annotations

import pytest

from last_newsletter_adapter_events.prefilter import has_date_signal
from last_newsletter_adapter_events.when import parse_when


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
