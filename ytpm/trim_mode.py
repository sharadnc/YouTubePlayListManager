"""
PURPOSE:
    Trim mode entrypoint — remove duplicate videos from one or more playlists.

INTERNAL LOGIC:
    Resolves playlist ids/titles and calls ops.cleanup.trim_duplicates.

EXAMPLE INVOCATION:
    from ytpm.trim_mode import trim_playlists
    trim_playlists(["PLxxx"])
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Optional

from ytpm.ops.cleanup import trim_duplicates
from ytpm.ops.playlists import find_playlist_by_title, get_client, list_playlists
from ytpm.youtube_client import YouTubeClient

logger = logging.getLogger(__name__)


def resolve_playlist_id(ref: str, *, client: Optional[YouTubeClient] = None) -> str:
    """
    PURPOSE:
        Resolve a playlist id or exact title to a playlist id.

    INTERNAL LOGIC:
        If ref looks like an id (starts with PL) and matches a listed playlist, use it;
        else match by exact title.

    EXAMPLE INVOCATION:
        resolve_playlist_id("Favorites")
    """
    yt = get_client(client)
    playlists = list_playlists(yt)
    for pl in playlists:
        if pl.id == ref:
            return pl.id
    by_title = find_playlist_by_title(ref, client=yt)
    if by_title:
        return by_title.id
    # Allow PL ids not returned in mine list (edge cases)
    if ref.startswith("PL") or ref.startswith("UU") or ref.startswith("LL"):
        return ref
    raise ValueError(f"Playlist not found: {ref}")


def trim_playlists(
    refs: Iterable[str],
    *,
    client: Optional[YouTubeClient] = None,
) -> List[tuple[str, int]]:
    """
    PURPOSE:
        Remove duplicates from each referenced playlist.

    INTERNAL LOGIC:
        Resolves refs; trim_duplicates each; returns (playlist_id, removed) pairs.

    EXAMPLE INVOCATION:
        trim_playlists(["PLxxx", "My Mix"])
    """
    yt = get_client(client)
    results: List[tuple[str, int]] = []
    for ref in refs:
        pid = resolve_playlist_id(ref, client=yt)
        removed = trim_duplicates(pid, client=yt)
        results.append((pid, removed))
        logger.info("Trim %s: removed %s duplicates", pid, removed)
    return results


def trim_all(*, client: Optional[YouTubeClient] = None) -> List[tuple[str, int]]:
    """
    PURPOSE:
        Trim duplicates from every playlist owned by the user.

    INTERNAL LOGIC:
        Lists all playlists; trims each.

    EXAMPLE INVOCATION:
        trim_all()
    """
    yt = get_client(client)
    return trim_playlists([p.id for p in list_playlists(yt)], client=yt)
