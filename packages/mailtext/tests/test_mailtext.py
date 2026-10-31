from __future__ import annotations

from email.header import Header
from email.message import EmailMessage

from mailtext import decode_header_value, extract_body_text


def test_decode_header_value_with_no_header_returns_empty_string() -> None:
    assert decode_header_value(None) == ""


def test_decode_header_value_passes_through_plain_ascii() -> None:
    assert decode_header_value("Hello World") == "Hello World"


def test_decode_header_value_decodes_rfc2047_encoded_words() -> None:
    encoded = Header("Café Newsletter", "utf-8").encode()

    assert decode_header_value(encoded) == "Café Newsletter"


def test_extract_body_text_prefers_plain_text() -> None:
    msg = EmailMessage()
    msg.set_content("Plain body.")

    assert extract_body_text(msg) == "Plain body."


def test_extract_body_text_falls_back_to_html_converted_to_text() -> None:
    msg = EmailMessage()
    msg.set_content("<html><body><p>Real content.</p></body></html>", subtype="html")

    assert "Real content." in extract_body_text(msg)


def test_extract_body_text_html_fallback_drops_script_content() -> None:
    html = "<html><body><script>evil()</script><p>Safe content.</p></body></html>"
    msg = EmailMessage()
    msg.set_content(html, subtype="html")

    text = extract_body_text(msg)

    assert "Safe content." in text
    assert "evil()" not in text


def test_extract_body_text_with_no_text_part_returns_empty_string() -> None:
    msg = EmailMessage()
    msg.set_content(b"\x00\x01binary", maintype="application", subtype="octet-stream")

    assert extract_body_text(msg) == ""
