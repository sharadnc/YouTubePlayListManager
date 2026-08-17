"""
PURPOSE:
    Tests for playlist/videos split persistence (50/50 default, skip bad sash).

INTERNAL LOGIC:
    Pure functions; no Tk window.

EXAMPLE INVOCATION:
    pytest tests/test_gui_prefs.py
"""

from __future__ import annotations

from ytpm.gui_prefs import (
    DEFAULT_SASH_FRAC,
    capture_sash_values,
    merge_sash_into_settings,
    resolve_sash_pos,
)


def test_first_launch_is_half() -> None:
    """PURPOSE: No saved split → playlists and videos each get 50% height."""
    assert resolve_sash_pos({}, 800) == 400
    assert resolve_sash_pos({"sash": 0}, 800) == int(round(800 * DEFAULT_SASH_FRAC))


def test_restore_saved_frac_and_pixels() -> None:
    """PURPOSE: Next launch uses the user's last split."""
    assert resolve_sash_pos({"sash_frac": 0.25}, 800) == 200
    assert resolve_sash_pos({"sash": 300}, 800) == 300


def test_unmapped_pane_retries() -> None:
    """PURPOSE: Do not apply a split until the paned window has a real height."""
    assert resolve_sash_pos({"sash_frac": 0.5}, 1) is None


def test_capture_skips_collapsed_sash() -> None:
    """PURPOSE: Do not persist sash=0 from a layout that is not ready yet."""
    assert capture_sash_values(0, 800) is None
    assert capture_sash_values(400, 800) == (400, 0.5)
    settings = {"sash": 400, "sash_frac": 0.5}
    merge_sash_into_settings(settings, 0, 800)
    assert settings["sash"] == 400
    merge_sash_into_settings(settings, 240, 800)
    assert settings["sash"] == 240
    assert settings["sash_frac"] == 0.3
