from __future__ import annotations

from datetime import UTC, date, datetime

from last_newsletter_adapter_publish.render import render_html
from last_newsletter_core.entities import Cadence, Digest, Theme


def _digest(themes: tuple[Theme, ...]) -> Digest:
    return Digest(
        period_start=datetime(2026, 10, 31, tzinfo=UTC),
        period_end=datetime(2026, 11, 7, tzinfo=UTC),
        cadence=Cadence.WEEKLY,
        themes=themes,
        total_messages=len(themes),
        total_sources=len(themes),
    )


def test_a_single_source_theme_shows_no_sources_badge() -> None:
    html = render_html(_digest((Theme(title="One newsletter", summary="...", source_count=1),)))

    assert "badge-sources" not in html


def test_a_multi_source_theme_shows_the_sources_badge() -> None:
    html = render_html(
        _digest((Theme(title="Merged across senders", summary="...", source_count=3),))
    )

    assert "3 sources" in html


def test_a_theme_with_a_deadline_gets_the_urgent_card_class() -> None:
    html = render_html(
        _digest(
            (
                Theme(
                    title="Conference next week",
                    summary="...",
                    source_count=1,
                    relevant_until=date(2026, 11, 10),
                ),
            )
        )
    )

    assert 'class="card urgent"' in html
    assert "until 2026-11-10" in html


def test_a_recurring_theme_gets_the_recurring_card_class() -> None:
    html = render_html(
        _digest((Theme(title="Ongoing saga", summary="...", source_count=1, streak=3),))
    )

    assert 'class="card recurring"' in html
    assert "3&times; in a row" in html


def test_every_value_is_html_escaped() -> None:
    html = render_html(
        _digest((Theme(title="<script>alert(1)</script>", summary="x", source_count=1),))
    )

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
