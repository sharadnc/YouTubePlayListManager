"""
PURPOSE:
    Compute duration and channel statistics for a playlist.

INTERNAL LOGIC:
    Enriches items; aggregates total/average/longest/shortest/unique channels.

EXAMPLE INVOCATION:
    from ytpm.ops.stats import playlist_stats
    print(playlist_stats("PLxxx"))
"""

from __future__ import annotations

import logging
from typing import Optional

from ytpm.models import PlaylistStats
from ytpm.ops.playlists import get_client
from ytpm.youtube_client import YouTubeClient

logger = logging.getLogger(__name__)


def format_duration(seconds: int) -> str:
    """
    PURPOSE:
        Format seconds as H:MM:SS or M:SS for display.

    INTERNAL LOGIC:
        Integer division into hours/minutes/seconds.

    EXAMPLE INVOCATION:
        format_duration(3725)  # "1:02:05"
    """
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def playlist_stats(
    playlist_id: str,
    *,
    client: Optional[YouTubeClient] = None,
) -> PlaylistStats:
    """
    PURPOSE:
        Build aggregate stats for all videos in a playlist.

    INTERNAL LOGIC:
        Enriches durations; skips zero-duration when picking shortest if possibles.

    EXAMPLE INVOCATION:
        s = playlist_stats("PLxxx")
        print(s.total_seconds, s.unique_channels)
    """
    yt = get_client(client)
    items = yt.enrich_items(yt.list_playlist_items(playlist_id))
    if not items:
        return PlaylistStats()
    durations = [(it.title, it.duration_seconds) for it in items]
    total = sum(d for _, d in durations)
    channels = {it.channel_title for it in items if it.channel_title}
    longest = max(durations, key=lambda x: x[1])
    nonzero = [d for d in durations if d[1] > 0]
    shortest = min(nonzero, key=lambda x: x[1]) if nonzero else min(durations, key=lambda x: x[1])
    avg = total / len(items) if items else 0.0
    stats = PlaylistStats(
        item_count=len(items),
        total_seconds=total,
        average_seconds=avg,
        longest_title=longest[0],
        longest_seconds=longest[1],
        shortest_title=shortest[0],
        shortest_seconds=shortest[1],
        unique_channels=len(channels),
    )
    logger.info("Stats for %s: %s items, %ss total", playlist_id, stats.item_count, stats.total_seconds)
    return stats
