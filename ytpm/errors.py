"""
PURPOSE:
    Format Google API / OAuth exceptions into short user-facing messages.

INTERNAL LOGIC:
    Detects HttpError 403 accessNotConfigured and returns enable-API guidance;
    otherwise returns a truncated exception string.

EXAMPLE INVOCATION:
    from ytpm.errors import format_api_error
    messagebox.showerror("Error", format_api_error(exc))
"""

from __future__ import annotations

import re
from typing import Any


class QuotaExceededError(RuntimeError):
    """
    PURPOSE:
        Raised when YouTube Data API daily quota is exhausted.

    INTERNAL LOGIC:
        Carries a user-facing recovery message (reset time, quota increase, Manual sort).

    EXAMPLE INVOCATION:
        raise QuotaExceededError("Daily quota used up")
    """


QUOTA_HELP: str = (
    "YouTube Data API daily quota is used up (default 10,000 units/day).\n\n"
    "Writes cost ~50 units per video. A 64-video sort needs ~3,200 units; "
    "delete-and-re-add needs ~6,400 and can empty a playlist if it fails mid-way.\n\n"
    "What to do:\n"
    "1. Wait until midnight US Pacific Time — quota resets daily.\n"
    "2. Request a higher quota in Google Cloud:\n"
    "   https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas\n"
    "3. In YouTube Studio, open the playlist → Sort → Manual, then retry. "
    "Manual sort uses position updates only (half the cost, original playlist stays intact).\n\n"
    "The original playlist is not replaced. If a list_mode file was saved, use "
    "List Mode: Apply after quota resets."
)


def is_quota_exceeded(exc: BaseException) -> bool:
    """
    PURPOSE:
        Detect YouTube Data API quota / daily-limit errors.

    INTERNAL LOGIC:
        Matches quotaExceeded, dailyLimitExceeded, and the public 403 message.

    EXAMPLE INVOCATION:
        if is_quota_exceeded(exc): raise QuotaExceededError(...)
    """
    text = str(exc)
    lowered = text.lower()
    return (
        "quotaexceeded" in lowered.replace(" ", "")
        or "dailylimitexceeded" in lowered.replace(" ", "")
        or ("exceeded" in lowered and "quota" in lowered)
    )


class PlaylistOrderError(RuntimeError):
    """
    PURPOSE:
        Raised when YouTube auto-sort prevents a custom playlist order from sticking.

    INTERNAL LOGIC:
        Carries a user-facing message including a Studio link.

    EXAMPLE INVOCATION:
        raise PlaylistOrderError("Set Sort to Manual in YouTube Studio")
    """


def is_manual_sort_required(exc: BaseException) -> bool:
    """
    PURPOSE:
        Detect YouTube's 'playlist must be Manual sort to set position' error.

    INTERNAL LOGIC:
        Matches reason/message tokens from playlistItems.update/insert.

    EXAMPLE INVOCATION:
        if is_manual_sort_required(exc): rebuild_order()
    """
    text = str(exc)
    return "manualSortRequired" in text or "need to be MANUAL" in text or "manual sorting" in text.lower()


def format_api_error(exc: BaseException) -> str:
    """
    PURPOSE:
        Convert an API/auth exception into a readable dialog message.

    INTERNAL LOGIC:
        Special-cases YouTube API not enabled (403 accessNotConfigured);
        strips verbose HttpError wrappers when possible.

    EXAMPLE INVOCATION:
        format_api_error(HttpError(...))
    """
    text = str(exc)
    if isinstance(exc, QuotaExceededError):
        return str(exc) if str(exc).strip() else QUOTA_HELP
    if is_quota_exceeded(exc):
        return QUOTA_HELP
    if isinstance(exc, PlaylistOrderError):
        return str(exc)
    if is_manual_sort_required(exc):
        return (
            "YouTube will not set video positions unless the playlist Sort is Manual.\n\n"
            "Open YouTube Studio → the playlist → Sort → Manual, then retry.\n"
            "The app will not delete/re-add videos (that burns quota and can empty the playlist)."
        )
    if "accessNotConfigured" in text or "has not been used in project" in text:
        match = re.search(r"project[= ](\d+)", text)
        project = match.group(1) if match else None
        url = (
            f"https://console.developers.google.com/apis/api/youtube.googleapis.com/overview?project={project}"
            if project
            else "https://console.cloud.google.com/apis/library/youtube.googleapis.com"
        )
        return (
            "YouTube Data API v3 is not enabled for your Google Cloud project.\n\n"
            "1. Open this link and click Enable:\n"
            f"{url}\n\n"
            "2. Wait 1–2 minutes, then click Refresh in the app."
        )
    # Compact typical googleapiclient HttpError
    if "HttpError" in type(exc).__name__ or "HttpError" in text:
        reason = getattr(exc, "reason", None) or ""
        status = getattr(getattr(exc, "resp", None), "status", "")
        if reason:
            return f"YouTube API error {status}: {reason}\n\n{text[:400]}"
        return text[:600]
    return text[:600]


def is_api_not_enabled(exc: Any) -> bool:
    """
    PURPOSE:
        Detect the 'YouTube Data API not enabled' configuration error.

    INTERNAL LOGIC:
        Searches exception string for accessNotConfigured / not been used.

    EXAMPLE INVOCATION:
        if is_api_not_enabled(exc): ...
    """
    text = str(exc)
    return "accessNotConfigured" in text or "has not been used in project" in text
