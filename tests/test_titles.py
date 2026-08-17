"""
PURPOSE:
    Tests for title whitespace collapse helpers.

INTERNAL LOGIC:
    normalize_title collapses runs of whitespace; title_needs_space_collapse
    is true only when collapse would change the string.

EXAMPLE INVOCATION:
    pytest tests/test_titles.py
"""

from __future__ import annotations

from ytpm.titles import normalize_title, title_needs_space_collapse


def test_normalize_title_collapses_spaces() -> None:
    """PURPOSE: Consecutive spaces become one. INTERNAL LOGIC: regex \\s+."""
    assert normalize_title("Foo   Bar") == "Foo Bar"
    assert normalize_title("  A   B\tC  ") == "A B C"
    assert normalize_title("") == ""


def test_title_needs_space_collapse() -> None:
    """PURPOSE: Detect titles that still have extra whitespace."""
    assert title_needs_space_collapse("Foo  Bar") is True
    assert title_needs_space_collapse("Foo Bar") is False
    assert title_needs_space_collapse("   ") is False
    assert title_needs_space_collapse("") is False
