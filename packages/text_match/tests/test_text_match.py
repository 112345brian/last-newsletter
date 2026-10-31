from __future__ import annotations

import pytest

from text_match import find_terms, normalize_term


def test_normalize_term_collapses_whitespace_and_casefolds() -> None:
    assert normalize_term("  Brother   Hood  ") == "brother hood"


def test_normalize_term_rejects_blank() -> None:
    with pytest.raises(ValueError, match="empty or blank"):
        normalize_term("   ")


def test_normalize_term_rejects_control_characters() -> None:
    with pytest.raises(ValueError, match="control characters"):
        normalize_term("brother\x00")


def test_normalize_term_rejects_no_letters_or_digits() -> None:
    with pytest.raises(ValueError, match="no letters or digits"):
        normalize_term("---")


def test_find_terms_matches_whole_word_with_punctuation_or_hyphen() -> None:
    terms = [normalize_term("brother")]

    assert find_terms("my-brother said hello", terms) == ["brother"]
    assert find_terms("Brother, is that you?", terms) == ["brother"]
    assert find_terms("brother's keeper", terms) == ["brother"]


def test_find_terms_does_not_match_a_longer_word_containing_the_term() -> None:
    terms = [normalize_term("brother")]

    assert find_terms("brotherhood", terms) == []


def test_find_terms_returns_terms_in_list_order() -> None:
    terms = [normalize_term("second"), normalize_term("first")]

    assert find_terms("first and second appear here", terms) == ["second", "first"]


def test_find_terms_on_empty_text_returns_empty_list() -> None:
    assert find_terms("", [normalize_term("anything")]) == []


def test_multi_word_term_matches_any_whitespace_run() -> None:
    term = normalize_term("new york")

    assert find_terms("I live in New   York.", [term]) == [term]
