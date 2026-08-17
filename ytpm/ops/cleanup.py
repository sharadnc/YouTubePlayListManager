"""
PURPOSE:
    Remove duplicate playlist items and find/remove unavailable (deleted) videos.

INTERNAL LOGIC:
    Trim keeps first occurrence per video_id.
    Broken means YouTube replaced the row with a placeholder title
    ("Deleted video" / "Private video"). Unlisted videos that still play are not broken.

EXAMPLE INVOCATION:
    from ytpm.ops.cleanup import trim_duplicates, find_broken
    trim_duplicates("PLxxx")
"""

from __future__ import annotations

import logging
from typing import List, Optional, Set

from ytpm.models import PlaylistItem
from ytpm.ops.playlists import get_client
from ytpm.youtube_client import YouTubeClient, is_placeholder_title

logger = logging.getLogger(__name__)

_DELETED_TITLES: Set[str] = {
    "deleted video",
    "[deleted video]",
    "unavailable video",
    "[unavailable video]",
}
_PRIVATE_PLACEHOLDER_TITLES: Set[str] = {
    "private video",
    "[private video]",
}


def broken_reason(item: PlaylistItem) -> Optional[str]:
    """
    PURPOSE:
        Return a short reason if a playlist item is unplayable, else None.

    INTERNAL LOGIC:
        Trusts YouTube playlist placeholder titles ("Deleted video", "Private video")
        and missing video ids. Does NOT treat videos.list misses or unlisted/private
        as broken — those videos often still play on YouTube via the playlist.

    EXAMPLE INVOCATION:
        broken_reason(item)  # "deleted" or None
    """
    video_id = (item.video_id or "").strip()
    title = (item.title or "").strip().lower()
    if not video_id:
        return "missing video id"
    if title in _DELETED_TITLES:
        return "deleted"
    if title in _PRIVATE_PLACEHOLDER_TITLES:
        return "inaccessible private"
    if is_placeholder_title(item.title):
        return "unavailable"
    return None


def trim_duplicates(
    playlist_id: str,
    *,
    client: Optional[YouTubeClient] = None,
) -> int:
    """
    PURPOSE:
        Remove duplicate video ids from a playlist, keeping the first occurrence.

    INTERNAL LOGIC:
        Walks items in position order; deletes later duplicates.

    EXAMPLE INVOCATION:
        removed = trim_duplicates("PLxxx")
    """
    yt = get_client(client)
    items = yt.list_playlist_items(playlist_id)
    seen: Set[str] = set()
    removed = 0
    for item in items:
        vid = (item.video_id or "").strip()
        if not vid:
            continue
        if vid in seen:
            yt.delete_playlist_item(item.id)
            removed += 1
        else:
            seen.add(vid)
    logger.info("Trimmed %s duplicates from %s", removed, playlist_id)
    return removed


def find_broken(
    playlist_id: str,
    *,
    include_private: bool = False,
    include_unlisted: bool = False,
    include_deleted: bool = True,
    client: Optional[YouTubeClient] = None,
) -> List[PlaylistItem]:
    """
    PURPOSE:
        Scan a playlist for unplayable entries (and optionally list private/unlisted).

    INTERNAL LOGIC:
        Enriches via videos.list. Always includes deleted/unavailable when
        include_deleted. Optional flags add videos that still exist but are
        private or unlisted (review only — they are not dead links).

    EXAMPLE INVOCATION:
        find_broken("PLxxx")
        find_broken("PLxxx", include_unlisted=True)
    """
    yt = get_client(client)
    items = yt.enrich_items(yt.list_playlist_items(playlist_id))
    broken: List[PlaylistItem] = []
    for item in items:
        reason = broken_reason(item)
        status = (item.privacy_status or "").lower()
        if include_deleted and reason:
            broken.append(item)
            continue
        if reason:
            continue
        if include_private and status == "private":
            broken.append(item)
        elif include_unlisted and status == "unlisted":
            broken.append(item)
    logger.info("Find broken on %s: %s item(s)", playlist_id, len(broken))
    return broken


def remove_broken(
    playlist_id: str,
    *,
    include_private: bool = False,
    include_unlisted: bool = False,
    include_deleted: bool = True,
    client: Optional[YouTubeClient] = None,
) -> int:
    """
    PURPOSE:
        Find broken items and delete them from the playlist.

    INTERNAL LOGIC:
        find_broken then delete each playlistItem id.

    EXAMPLE INVOCATION:
        n = remove_broken("PLxxx")
    """
    yt = get_client(client)
    broken = find_broken(
        playlist_id,
        include_private=include_private,
        include_unlisted=include_unlisted,
        include_deleted=include_deleted,
        client=yt,
    )
    for item in broken:
        yt.delete_playlist_item(item.id)
    logger.info("Removed %s broken items from %s", len(broken), playlist_id)
    return len(broken)
