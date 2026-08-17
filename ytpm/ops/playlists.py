"""
PURPOSE:
    Playlist-level CRUD helpers (list, create, rename, delete, clear).

INTERNAL LOGIC:
    Delegates to YouTubeClient; clear removes every playlistItem.

EXAMPLE INVOCATION:
    from ytpm.ops.playlists import create_playlist, clear_playlist
    create_playlist("My Mix")
"""

from __future__ import annotations

import logging
from typing import List, Optional

from ytpm.models import Playlist
from ytpm.youtube_client import YouTubeClient

logger = logging.getLogger(__name__)


def get_client(client: Optional[YouTubeClient] = None) -> YouTubeClient:
    """
    PURPOSE:
        Return provided client or construct from OAuth.

    INTERNAL LOGIC:
        Identity if client given; else YouTubeClient.from_auth().

    EXAMPLE INVOCATION:
        get_client()
    """
    return client or YouTubeClient.from_auth()


def list_playlists(client: Optional[YouTubeClient] = None) -> List[Playlist]:
    """
    PURPOSE:
        List all playlists for the authenticated user.

    INTERNAL LOGIC:
        Forwards to YouTubeClient.list_my_playlists.

    EXAMPLE INVOCATION:
        list_playlists()
    """
    return get_client(client).list_my_playlists()


def create_playlist(
    title: str,
    *,
    description: str = "",
    privacy: str = "private",
    client: Optional[YouTubeClient] = None,
) -> Playlist:
    """
    PURPOSE:
        Create a new playlist.

    INTERNAL LOGIC:
        Validates non-empty title; inserts via API.

    EXAMPLE INVOCATION:
        create_playlist("Favorites 2026")
    """
    title = title.strip()
    if not title:
        raise ValueError("Playlist title must not be empty")
    pl = get_client(client).create_playlist(title, description=description, privacy=privacy)
    logger.info("Created playlist %s (%s)", pl.title, pl.id)
    return pl


def rename_playlist(
    playlist_id: str,
    new_title: str,
    *,
    client: Optional[YouTubeClient] = None,
) -> Playlist:
    """
    PURPOSE:
        Rename a playlist by id.

    INTERNAL LOGIC:
        Validates title; calls client.rename_playlist.

    EXAMPLE INVOCATION:
        rename_playlist("PLxxx", "New Name")
    """
    new_title = new_title.strip()
    if not new_title:
        raise ValueError("New title must not be empty")
    pl = get_client(client).rename_playlist(playlist_id, new_title)
    logger.info("Renamed playlist %s to %s", playlist_id, new_title)
    return pl


def delete_playlist(
    playlist_id: str,
    *,
    confirm_title: str,
    expected_title: str,
    client: Optional[YouTubeClient] = None,
) -> None:
    """
    PURPOSE:
        Delete a playlist after confirming the typed name matches.

    INTERNAL LOGIC:
        Raises if confirm_title != expected_title; then deletes.

    EXAMPLE INVOCATION:
        delete_playlist("PLxxx", confirm_title="My Mix", expected_title="My Mix")
    """
    if confirm_title.strip() != expected_title.strip():
        raise ValueError("Confirmation title does not match playlist name")
    get_client(client).delete_playlist(playlist_id)
    logger.info("Deleted playlist %s (%s)", expected_title, playlist_id)


def set_privacy(
    playlist_id: str,
    privacy: str,
    *,
    client: Optional[YouTubeClient] = None,
) -> Playlist:
    """
    PURPOSE:
        Change a playlist's privacy status.

    INTERNAL LOGIC:
        Forwards to YouTubeClient.set_playlist_privacy.

    EXAMPLE INVOCATION:
        set_privacy("PLxxx", "unlisted")
    """
    pl = get_client(client).set_playlist_privacy(playlist_id, privacy)
    logger.info("Privacy for %s set to %s", playlist_id, privacy)
    return pl


def set_description(
    playlist_id: str,
    description: str,
    *,
    client: Optional[YouTubeClient] = None,
) -> Playlist:
    """
    PURPOSE:
        Update a playlist description (one playlists.update when text changes).

    INTERNAL LOGIC:
        Forwards to YouTubeClient.set_playlist_description.

    EXAMPLE INVOCATION:
        set_description("PLxxx", "Favorites from 2026")
    """
    pl = get_client(client).set_playlist_description(playlist_id, description)
    logger.info("Description updated for %s", playlist_id)
    return pl


def clear_playlist(
    playlist_id: str,
    *,
    dry_run: bool = False,
    client: Optional[YouTubeClient] = None,
) -> int:
    """
    PURPOSE:
        Remove all videos from a playlist without deleting the playlist.

    INTERNAL LOGIC:
        Snapshots membership for Undo. Dry-run also writes the list-mode file
        and returns without deletes (0 write quota).

    EXAMPLE INVOCATION:
        n = clear_playlist("PLxxx", dry_run=True)
    """
    yt = get_client(client)
    items = yt.list_playlist_items(playlist_id)
    from ytpm.list_mode import snapshot_playlist, write_sorted_list_file

    snapshot_playlist(playlist_id, playlist_id, items)
    if dry_run:
        write_sorted_list_file(playlist_id, playlist_id, items)
        logger.info("Dry-run clear %s: would delete %s items", playlist_id, len(items))
        return len(items)
    for item in items:
        yt.delete_playlist_item(item.id)
    logger.info("Cleared %s items from %s", len(items), playlist_id)
    return len(items)


def find_playlist_by_title(
    title: str,
    *,
    client: Optional[YouTubeClient] = None,
) -> Optional[Playlist]:
    """
    PURPOSE:
        Find first playlist whose title matches exactly (case-sensitive).

    INTERNAL LOGIC:
        Scans list_playlists for equality.

    EXAMPLE INVOCATION:
        find_playlist_by_title("Favorites")
    """
    for pl in list_playlists(client):
        if pl.title == title:
            return pl
    return None
