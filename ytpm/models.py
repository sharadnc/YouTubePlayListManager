"""
PURPOSE:
    Pydantic models for playlists, playlist items, and video metadata.

INTERNAL LOGIC:
    Lightweight DTOs used by youtube_client and ops modules.

EXAMPLE INVOCATION:
    from ytpm.models import Playlist
    p = Playlist(id="PL...", title="Favorites", item_count=10)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Playlist(BaseModel):
    """
    PURPOSE:
        Represent a YouTube playlist owned by the authenticated user.

    INTERNAL LOGIC:
        Maps API playlist resource fields used by the UI/CLI.

    EXAMPLE INVOCATION:
        Playlist(id="PLxxx", title="Watch Later Alt", item_count=3, privacy="private")
    """

    id: str
    title: str
    description: str = ""
    item_count: int = 0
    privacy: str = "private"
    published_at: Optional[datetime] = None


class PlaylistItem(BaseModel):
    """
    PURPOSE:
        Represent one entry in a playlist (position + video reference).

    INTERNAL LOGIC:
        Holds playlistItem id, video id, title/channel, position, and date added.

    EXAMPLE INVOCATION:
        PlaylistItem(id="UExxx", video_id="dQw4", title="Song", position=0)
    """

    id: str
    video_id: str
    title: str = ""
    channel_title: str = ""
    position: int = 0
    published_at: Optional[datetime] = None
    privacy_status: str = "public"
    duration_iso: str = ""
    duration_seconds: int = 0


class VideoMeta(BaseModel):
    """
    PURPOSE:
        Extra video details from videos.list (duration, channel, privacy).

    INTERNAL LOGIC:
        Used when enriching playlist items and computing stats.

    EXAMPLE INVOCATION:
        VideoMeta(video_id="abc", title="T", channel_title="C", duration_seconds=120)
    """

    video_id: str
    title: str = ""
    channel_title: str = ""
    duration_iso: str = ""
    duration_seconds: int = 0
    privacy_status: str = "public"
    exists: bool = True


class PlaylistStats(BaseModel):
    """
    PURPOSE:
        Aggregate duration/channel statistics for a playlist.

    INTERNAL LOGIC:
        Computed by ops.stats from enriched PlaylistItem list.

    EXAMPLE INVOCATION:
        PlaylistStats(item_count=5, total_seconds=600, unique_channels=2)
    """

    item_count: int = 0
    total_seconds: int = 0
    average_seconds: float = 0.0
    longest_title: str = ""
    longest_seconds: int = 0
    shortest_title: str = ""
    shortest_seconds: int = 0
    unique_channels: int = 0


class ListModeLine(BaseModel):
    """
    PURPOSE:
        One parsed line from a list-mode text file.

    INTERNAL LOGIC:
        video_id is required; playlist_item_id may be empty for new inserts.

    EXAMPLE INVOCATION:
        ListModeLine(video_id="abc", title="T", channel="C", playlist_item_id="UEx")
    """

    video_id: str
    title: str = ""
    channel: str = ""
    playlist_item_id: str = ""
