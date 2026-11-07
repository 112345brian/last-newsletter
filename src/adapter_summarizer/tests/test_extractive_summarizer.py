from __future__ import annotations

from datetime import UTC, date, datetime

from last_newsletter_adapter_summarizer.extractive_summarizer import (
    EXCERPT_LIMIT,
    ExtractiveSummarizer,
)
from last_newsletter_core.entities import EmailMessage, Theme

_TODAY = date(2026, 11, 8)


def _message(
    *,
    message_id: str = "m1",
    subject: str = "Hello",
    body: str = "Some text.",
    sender: str = "a@example.com",
) -> EmailMessage:
    return EmailMessage(
        message_id=message_id,
        sender=sender,
        subject=subject,
        received_at=datetime(2026, 11, 7, tzinfo=UTC),
        body_text=body,
        source_label=sender,
    )


def _summarize(*messages: EmailMessage, prior: list[Theme] | None = None) -> list[Theme]:
    return ExtractiveSummarizer().summarize(list(messages), prior_themes=prior or [], today=_TODAY)


def test_one_theme_per_message_titled_by_subject_and_citing_its_id() -> None:
    themes = _summarize(
        _message(message_id="m1", subject="First"), _message(message_id="m2", subject="Second")
    )

    assert [t.title for t in themes] == ["First", "Second"]
    assert [t.source_message_ids for t in themes] == [("m1",), ("m2",)]
    assert all(t.source_count == 1 for t in themes)


def test_no_messages_gives_no_themes() -> None:
    assert _summarize() == []


def test_urls_are_stripped_from_the_summary() -> None:
    body = "Doors at 8. Tickets: https://track.example.com/c/abc123?uid=secret and http://x.test/y"

    summary = _summarize(_message(body=body))[0].summary

    assert "http" not in summary
    assert "secret" not in summary
    assert "Doors at 8." in summary


def test_whitespace_is_collapsed_and_boilerplate_lines_are_dropped() -> None:
    body = "View in browser\n\nBig   news\n\ntoday.\nUnsubscribe here\n"

    summary = _summarize(_message(body=body))[0].summary

    assert summary == "Big news today."


def test_long_body_is_cut_at_a_word_boundary_with_an_ellipsis() -> None:
    body = "word " * 500

    summary = _summarize(_message(body=body))[0].summary

    assert len(summary) <= EXCERPT_LIMIT + 1
    assert summary.endswith("…")
    assert not summary.removesuffix("…").endswith("wor")


def test_blank_subject_and_empty_body_get_placeholders() -> None:
    theme = _summarize(_message(subject="   ", body=" \n "))[0]

    assert theme.title == "(no subject)"
    assert theme.summary == "(no text)"


def test_nul_and_control_characters_are_removed() -> None:
    theme = _summarize(_message(subject="Hi\x00there", body="a\x00b\x07c"))[0]

    assert "\x00" not in theme.title
    assert "\x00" not in theme.summary
    assert "\x07" not in theme.summary


def test_body_that_is_only_urls_is_treated_as_empty() -> None:
    assert _summarize(_message(body="https://a.test/x https://b.test/y"))[0].summary == "(no text)"


def test_prior_themes_are_not_carried_forward() -> None:
    prior = Theme(title="Old", summary="x", source_count=3, theme_key="old")

    themes = _summarize(_message(), prior=[prior])

    assert [t.title for t in themes] == ["Hello"]
    assert not any(t.carried_forward for t in themes)
