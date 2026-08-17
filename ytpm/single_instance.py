"""
PURPOSE:
    Ensure only one YTPM GUI process runs (Run_YTPM.bat / pythonw stacking).

INTERNAL LOGIC:
    Windows named mutex. If another instance owns it, restore that window
    by title and return False so this process exits.

EXAMPLE INVOCATION:
    from ytpm.single_instance import acquire_or_activate
    if not acquire_or_activate():
        raise SystemExit(0)
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)

MUTEX_NAME: str = "Local\\IshaAnalytiks_YTPM"
WINDOW_TITLE: str = "YouTube Playlist Manager"
ERROR_ALREADY_EXISTS: int = 183
SW_RESTORE: int = 9

# Keep the mutex handle alive for the process lifetime (GC would release it).
_mutex_handle: Any = None


def _focus_existing() -> bool:
    """
    PURPOSE:
        Bring an already-running YTPM window to the foreground.

    INTERNAL LOGIC:
        FindWindowW by title; ShowWindow(SW_RESTORE) + SetForegroundWindow.

    EXAMPLE INVOCATION:
        _focus_existing()  # True if a window was found
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        find = user32.FindWindowW
        find.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        find.restype = wintypes.HWND
        hwnd = find(None, WINDOW_TITLE)
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception as exc:
        logger.warning("Could not focus existing YTPM window: %s", exc)
        return False


def acquire_or_activate() -> bool:
    """
    PURPOSE:
        Claim the single-instance mutex, or activate the existing GUI.

    INTERNAL LOGIC:
        CreateMutexW. ERROR_ALREADY_EXISTS → focus other window, return False.
        Non-Windows: always True (no mutex). Mutex failure: True (do not block).

    EXAMPLE INVOCATION:
        if not acquire_or_activate():
            return
    """
    global _mutex_handle
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        _mutex_handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            _focus_existing()
            logger.info("YTPM already running; focusing existing window")
            return False
        return True
    except Exception as exc:
        logger.warning("Single-instance mutex failed (continuing): %s", exc)
        return True


def mutex_held() -> Optional[Any]:
    """
    PURPOSE:
        Expose the mutex handle so tests can assert it was created.

    INTERNAL LOGIC:
        Returns the module-level handle (None if not acquired).

    EXAMPLE INVOCATION:
        mutex_held() is not None
    """
    return _mutex_handle
