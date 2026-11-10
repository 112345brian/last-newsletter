from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING, Self
from uuid import UUID

from concert_tracker_core.events import EventId
from concert_tracker_core.use_cases.list_upcoming_events import (
    UpcomingDay,
    UpcomingEvent,
    UpcomingEvents,
)

from last_newsletter_adapter_publish.email_publisher import SmtpConfig, SmtpEmailPublisher
from last_newsletter_adapter_publish.markdown_publisher import MarkdownPublisher
from last_newsletter_adapter_publish.render import MAX_TITLE_CHARS, render_html, render_markdown
from ranked_digest.entities import Cadence, Digest, Theme

if TYPE_CHECKING:
    from email.message import EmailMessage
    from pathlib import Path

_ID = EventId(UUID("12345678-1234-5678-1234-567812345678"))


def _digest(*themes: Theme) -> Digest:
    return Digest(
        period_start=datetime(2026, 12, 3, tzinfo=UTC),
        period_end=datetime(2026, 12, 10, tzinfo=UTC),
        cadence=Cadence.WEEKLY,
        themes=themes,
        total_messages=1,
        total_sources=1,
    )


def _theme() -> Theme:
    return Theme(title="A theme", summary="Words.", source_count=1)


def _event(**overrides: object) -> UpcomingEvent:
    base = UpcomingEvent(
        event_id=_ID, title="Band", day=date(2026, 12, 12), all_day=False, start=time(20)
    )
    return replace(base, **overrides)


def _window(*events: UpcomingEvent) -> UpcomingEvents:
    days = tuple(
        UpcomingDay(day=d, events=tuple(e for e in events if e.day == d))
        for d in sorted({e.day for e in events})
    )
    return UpcomingEvents(first_day=date(2026, 12, 10), last_day=date(2026, 12, 23), days=days)


def test_no_section_without_a_window_or_with_an_empty_one() -> None:
    for upcoming in (None, _window()):
        assert "Coming up" not in render_markdown(_digest(_theme()), upcoming)
        assert "Coming up" not in render_html(_digest(_theme()), upcoming)
        assert "upcoming" not in render_html(_digest(_theme()), upcoming).split("</style>")[1]


def test_existing_output_is_unchanged_without_a_window() -> None:
    assert render_markdown(_digest(_theme())) == render_markdown(_digest(_theme()), None)
    assert render_html(_digest(_theme())) == render_html(_digest(_theme()), None)


def test_markdown_section_sits_above_the_themes_with_the_uuid_in_a_comment() -> None:
    text = render_markdown(_digest(_theme()), _window(_event(venue="The Hall", city="Portland")))
    assert text.index("## Coming up") < text.index("## A theme")
    assert "### Sat Dec 12" in text
    assert "- **Band** — 8:00 PM — The Hall, Portland" in text
    assert text.count(str(_ID)) == 1
    assert f"<!-- event:{_ID} -->" in text
    visible = re.sub(r"<!--.*?-->", "", text)
    assert str(_ID) not in visible


def test_markdown_section_appears_even_with_no_themes() -> None:
    text = render_markdown(_digest(), _window(_event()))
    assert "No themes this period." in text
    assert "Band" in text


def test_html_section_keeps_the_uuid_in_a_data_attribute_only() -> None:
    html = render_html(_digest(_theme()), _window(_event()))
    assert f'data-event-id="{_ID}"' in html
    assert html.count(str(_ID)) == 1
    assert html.index("Coming up") < html.index("A theme")
    assert 'class="card upcoming"' in html


def test_when_text_for_each_shape() -> None:
    cases = {
        "all day": _event(all_day=True, start=None),
        "8:00 PM": _event(),
        "12:00 AM": _event(start=time(0)),
        "8:00 PM \N{EN DASH} 10:30 PM": _event(end=time(22, 30)),
        "10:00 PM \N{EN DASH} 2:00 AM Sun Dec 13": _event(
            start=time(22), end=time(2), end_day=date(2026, 12, 13)
        ),
        "12:00 PM, 3:30 PM, 7:00 PM": _event(
            start=time(12), showtimes=(time(12), time(15, 30), time(19))
        ),
    }
    for expected, event in cases.items():
        assert f" — {expected}" in render_markdown(_digest(), _window(event)), expected
        assert expected in render_html(_digest(), _window(event)), expected


def test_citation_count_shows_only_when_repeated() -> None:
    one = render_markdown(_digest(), _window(_event()))
    many = render_markdown(_digest(), _window(_event(mention_count=3)))
    assert "emails" not in one
    assert "in 3 emails" in many
    assert "in 3 emails" in render_html(_digest(), _window(_event(mention_count=3)))


def test_html_special_characters_are_escaped_everywhere() -> None:
    nasty = '<script>alert("x")</script> & "q"'
    event = _event(title=nasty, venue=nasty, city="<b>c</b>", url='https://e.test/?a="1"&b=<2>')
    html = render_html(_digest(), _window(event))
    assert "<script>" not in html
    assert "<b>c</b>" not in html
    assert "&lt;script&gt;" in html
    assert 'href="https://e.test/?a=&quot;1&quot;&amp;b=&lt;2&gt;"' in html


def test_markdown_special_characters_are_neutralised() -> None:
    event = _event(title="*Bold* [x](http://evil.test) <img src=x> `code` # h\n## injected")
    text = render_markdown(_digest(), _window(event))
    [line] = [ln for ln in text.splitlines() if "Bold" in ln]
    assert "\n" not in line
    assert r"\*Bold\*" in line
    assert r"\[x\]\(http://evil.test\)" in line
    assert r"\<img src=x\>" in line
    assert r"\`code\`" in line
    assert not any(ln.startswith("## injected") for ln in text.splitlines())


def test_unsafe_urls_are_dropped_and_safe_ones_kept() -> None:
    for url in ("javascript:alert(1)", "data:text/html,x", "ftp://e.test/a", "https://", "a b"):
        out = render_html(_digest(), _window(_event(url=url)))
        assert "href=" not in out, url
        assert "[link]" not in render_markdown(_digest(), _window(_event(url=url))), url
    good = _event(url="https://e.test/a(b)")
    assert 'href="https://e.test/a(b)"' in render_html(_digest(), _window(good))
    assert "[link](<https://e.test/a(b)>)" in render_markdown(_digest(), _window(good))


def test_very_long_titles_are_cut_in_both_renderers() -> None:
    event = _event(title="W" * 5000, venue="V" * 5000)
    html = render_html(_digest(), _window(event))
    text = render_markdown(_digest(), _window(event))
    assert len(html) < 20_000
    assert "W" * MAX_TITLE_CHARS not in html
    assert "…" in html
    assert "…" in text
    assert "W" * 200 not in text


def test_long_unbroken_titles_cannot_break_the_layout() -> None:
    assert "overflow-wrap" in render_html(_digest(), _window(_event()))


def test_the_markdown_publisher_writes_the_section(tmp_path: Path) -> None:
    MarkdownPublisher(tmp_path, upcoming=_window(_event())).publish(_digest(_theme()))
    [path] = tmp_path.glob("*.md")
    assert "## Coming up" in path.read_text()


class _Smtp:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        return None

    def send_message(self, message: EmailMessage) -> None:
        self.sent.append(message)


def test_the_email_carries_the_section_in_both_parts(tmp_path: Path) -> None:
    smtp = _Smtp()
    config = SmtpConfig("h", 465, "u", "p", "a@x.test", "b@x.test")
    publisher = SmtpEmailPublisher(
        config, sent_dir=tmp_path / "sent", smtp_factory=lambda _c: smtp, upcoming=_window(_event())
    )
    publisher.publish(_digest(_theme()))
    [message] = smtp.sent
    text = message.get_body(("plain",))
    html = message.get_body(("html",))
    assert text is not None
    assert html is not None
    assert "## Coming up" in str(text.get_content())
    assert "Coming up" in str(html.get_content())
