"""
PURPOSE:
    Add/remove/move/copy playlist items across playlists.

INTERNAL LOGIC:
    Uses YouTubeClient insert/delete; copy can skip duplicate video ids.

EXAMPLE INVOCATION:
    from ytpm.ops.items import copy_videos, move_videos
    copy_videos("PLsrc", "PLdst", ["vid1"], skip_duplicates=True)
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Optional, Set

from ytpm.models import PlaylistItem
from ytpm.ops.playlists import get_client
from ytpm.youtube_client import YouTubeClient

logger = logging.getLogger(__name__)


def add_video(
    playlist_id: str,
    video_id: str,
    *,
    position: Optional[int] = None,
    client: Optional[YouTubeClient] = None,
) -> PlaylistItem:
    """
    PURPOSE:
        Insert a single video into a playlist.

    INTERNAL LOGIC:
        Forwards to YouTubeClient.insert_video.

    EXAMPLE INVOCATION:
        add_video("PLxxx", "dQw4w9WgXcQ")
    """
    item = get_client(client).insert_video(playlist_id, video_id, position=position)
    logger.info("Added %s to %s as %s", video_id, playlist_id, item.id)
    return item


def remove_items(
    playlist_item_ids: Iterable[str],
    *,
    client: Optional[YouTubeClient] = None,
) -> int:
    """
    PURPOSE:
        Delete playlist items by playlistItem id.

    INTERNAL LOGIC:
        Deletes each id; returns successful count.

    EXAMPLE INVOCATION:
        remove_items(["UEx1", "UEx2"])
    """
    yt = get_client(client)
    count = 0
    for item_id in playlist_item_ids:
        yt.delete_playlist_item(item_id)
        count += 1
    logger.info("Removed %s playlist items", count)
    return count


def rename_video_title(
    video_id: str,
    new_title: str,
    *,
    client: Optional[YouTubeClient] = None,
) -> str:
    """
    PURPOSE:
        Change the YouTube title of a video you uploaded.

    INTERNAL LOGIC:
        Forwards to YouTubeClient.update_owned_video_title (50-unit write).

    EXAMPLE INVOCATION:
        rename_video_title("dQw4", "Fixed title")
    """
    title = get_client(client).update_owned_video_title(video_id, new_title)
    logger.info("Renamed video %s", video_id)
    return title


def move_videos(
    source_playlist_id: str,
    dest_playlist_id: str,
    items: List[PlaylistItem],
    *,
    client: Optional[YouTubeClient] = None,
) -> int:
    """
    PURPOSE:
        Move videos from one playlist to another (insert then delete source items).

    INTERNAL LOGIC:
        Inserts each video_id into dest; deletes source playlistItem ids.

    EXAMPLE INVOCATION:
        move_videos("PLa", "PLb", selected_items)
    """
    if source_playlist_id == dest_playlist_id:
        raise ValueError("Source and destination playlists must differ")
    yt = get_client(client)
    moved = 0
    for item in items:
        yt.insert_video(dest_playlist_id, item.video_id)
        yt.delete_playlist_item(item.id)
        moved += 1
    logger.info("Moved %s items from %s to %s", moved, source_playlist_id, dest_playlist_id)
    return moved


def copy_videos(
    dest_playlist_id: str,
    items: List[PlaylistItem],
    *,
    skip_duplicates: bool = True,
    client: Optional[YouTubeClient] = None,
) -> int:
    """
    PURPOSE:
        Copy videos into a destination playlist.

    INTERNAL LOGIC:
        Optionally skips video ids already present in dest; inserts the rest.

    EXAMPLE INVOCATION:
        copy_videos("PLdst", items, skip_duplicates=True)
    """
    yt = get_client(client)
    existing: Set[str] = set()
    if skip_duplicates:
        existing = {i.video_id for i in yt.list_playlist_items(dest_playlist_id)}
    copied = 0
    for item in items:
        if skip_duplicates and item.video_id in existing:
            continue
        yt.insert_video(dest_playlist_id, item.video_id)
        existing.add(item.video_id)
        copied += 1
    logger.info("Copied %s items into %s", copied, dest_playlist_id)
    return copied


def list_items(
    playlist_id: str,
    *,
    enrich: bool = False,
    client: Optional[YouTubeClient] = None,
) -> List[PlaylistItem]:
    """
    PURPOSE:
        List playlist items, optionally enriched with duration/privacy.

    INTERNAL LOGIC:
        list_playlist_items then optional enrich_items.

    EXAMPLE INVOCATION:
        list_items("PLxxx", enrich=True)
    """
    yt = get_client(client)
    items = yt.list_playlist_items(playlist_id)
    if enrich:
        return yt.enrich_items(items)
    return items
