"""
PURPOSE:
    Playlist/videos split math for gui_settings.json (no Tk dependency).

INTERNAL LOGIC:
    Stores both a pixel sash and a fraction of the paned-window height.
    Invalid or unmapped values fall back to a 50/50 split.

EXAMPLE INVOCATION:
    pos = resolve_sash_pos({}, pane_height=800)
    # 400
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

DEFAULT_SASH_FRAC: float = 0.5
MIN_SASH_FRAC: float = 0.12
MAX_SASH_FRAC: float = 0.88
MIN_SPLIT_HEIGHT: int = 80


def clamp_sash_frac(frac: float) -> float:
    """
    PURPOSE:
        Keep the playlist/videos split inside a usable range.

    INTERNAL LOGIC:
        Clamps to MIN_SASH_FRAC..MAX_SASH_FRAC so neither pane collapses.

    EXAMPLE INVOCATION:
        clamp_sash_frac(0.01)  # 0.12
    """
    return min(MAX_SASH_FRAC, max(MIN_SASH_FRAC, frac))


def resolve_sash_pos(settings: Mapping[str, Any], pane_height: int) -> Optional[int]:
    """
    PURPOSE:
        Pixel sash for ttk.Panedwindow: saved preference or 50/50 default.

    INTERNAL LOGIC:
        1. If the pane is not laid out yet, return None (caller should retry).
        2. Prefer sash_frac when it is a finite ratio in (0, 1).
        3. Else use sash pixels when they fall inside the pane.
        4. Else return half the pane height (first launch / corrupt save).

    EXAMPLE INVOCATION:
        resolve_sash_pos({"sash_frac": 0.4}, 1000)  # 400
        resolve_sash_pos({}, 800)  # 400
        resolve_sash_pos({"sash": 0}, 50)  # None
    """
    if pane_height < MIN_SPLIT_HEIGHT:
        return None
    frac = _saved_frac(settings)
    if frac is not None:
        return int(round(pane_height * clamp_sash_frac(frac)))
    sash = _saved_pixels(settings)
    if sash is not None and 0 < sash < pane_height:
        return sash
    return int(round(pane_height * DEFAULT_SASH_FRAC))


def capture_sash_values(
    sash_pos: int,
    pane_height: int,
) -> Optional[Tuple[int, float]]:
    """
    PURPOSE:
        Record a user-dragged split only when both panes are visible.

    INTERNAL LOGIC:
        Rejects unmapped height and a sash at 0 or at the pane bottom.

    EXAMPLE INVOCATION:
        capture_sash_values(400, 800)  # (400, 0.5)
        capture_sash_values(0, 800)  # None
    """
    if pane_height < MIN_SPLIT_HEIGHT:
        return None
    if sash_pos <= 0 or sash_pos >= pane_height:
        return None
    frac = clamp_sash_frac(sash_pos / float(pane_height))
    return sash_pos, round(frac, 4)


def _saved_frac(settings: Mapping[str, Any]) -> Optional[float]:
    """
    PURPOSE:
        Parse sash_frac from settings if it is a usable ratio.

    INTERNAL LOGIC:
        Accepts int/float in (0, 1) exclusive of the collapsed edges.

    EXAMPLE INVOCATION:
        _saved_frac({"sash_frac": 0.5})  # 0.5
    """
    raw = settings.get("sash_frac")
    try:
        frac = float(raw)
    except (TypeError, ValueError):
        return None
    if 0.0 < frac < 1.0:
        return frac
    return None


def _saved_pixels(settings: Mapping[str, Any]) -> Optional[int]:
    """
    PURPOSE:
        Parse legacy sash pixel position from settings.

    INTERNAL LOGIC:
        Returns None when missing or not an integer-like value.

    EXAMPLE INVOCATION:
        _saved_pixels({"sash": 400})  # 400
    """
    raw = settings.get("sash")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def merge_sash_into_settings(
    settings: Dict[str, Any],
    sash_pos: int,
    pane_height: int,
) -> Dict[str, Any]:
    """
    PURPOSE:
        Update settings with a valid split; leave previous values if invalid.

    INTERNAL LOGIC:
        capture_sash_values must succeed before sash / sash_frac are written.

    EXAMPLE INVOCATION:
        merge_sash_into_settings({}, 400, 800)
        # {"sash": 400, "sash_frac": 0.5}
    """
    captured = capture_sash_values(sash_pos, pane_height)
    if captured is None:
        return settings
    pos, frac = captured
    settings["sash"] = pos
    settings["sash_frac"] = frac
    return settings
