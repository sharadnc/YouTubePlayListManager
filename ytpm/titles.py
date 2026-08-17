"""
PURPOSE:
    Normalize video/playlist titles (collapse consecutive whitespace).

INTERNAL LOGIC:
    Replaces any run of whitespace with a single space and strips ends.

EXAMPLE INVOCATION:
    from ytpm.titles import normalize_title
    normalize_title("Foo   Bar")  # "Foo Bar"
"""

from __future__ import annotations

import re

_MULTI_SPACE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """
    PURPOSE:
        Collapse consecutive spaces/tabs/newlines in a title to one space.

    INTERNAL LOGIC:
        Regex \\s+ → single space; strip leading/trailing whitespace.

    EXAMPLE INVOCATION:
        normalize_title("  A   B\\tC  ")  # "A B C"
    """
    return _MULTI_SPACE.sub(" ", title or "").strip()


def title_needs_space_collapse(title: str) -> bool:
    """
    PURPOSE:
        Detect titles that would change if consecutive whitespace were collapsed.

    INTERNAL LOGIC:
        True when normalize_title(title) differs from the original string.

    EXAMPLE INVOCATION:
        title_needs_space_collapse("Foo  Bar")  # True
        title_needs_space_collapse("Foo Bar")  # False
    """
    raw = title or ""
    collapsed = normalize_title(raw)
    return bool(collapsed) and collapsed != raw
