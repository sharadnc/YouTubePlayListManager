"""
PURPOSE:
    Export playlists to structured JSON files.

INTERNAL LOGIC:
    Lists items, enriches metadata, writes UTF-8 JSON under export dir.

EXAMPLE INVOCATION:
    from ytpm.ops.export import export_playlist_json
    path = export_playlist_json("PLxxx", title="Favorites")
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ytpm.config import get_settings
from ytpm.models import PlaylistItem
from ytpm.ops.playlists import get_client
from ytpm.youtube_client import YouTubeClient

logger = logging.getLogger(__name__)


def _safe_filename(name: str) -> str:
    """
    PURPOSE:
        Sanitize a playlist title for use as a filename stem.

    INTERNAL LOGIC:
        Replaces non-alphanumeric characters with underscore; truncates.

    EXAMPLE INVOCATION:
        _safe_filename("My Mix / 2026")  # "My_Mix_2026"
    """
    cleaned = re.sub(r"[^\w\-]+", "_", name.strip(), flags=re.UNICODE)
    return (cleaned or "playlist")[:80]


def items_to_export_dicts(items: List[PlaylistItem]) -> List[Dict[str, Any]]:
    """
    PURPOSE:
        Convert PlaylistItem models to JSON-serializable export rows.

    INTERNAL LOGIC:
        Includes title, channel, duration, video id, position, privacy.

    EXAMPLE INVOCATION:
        items_to_export_dicts(items)
    """
    rows: List[Dict[str, Any]] = []
    for item in items:
        rows.append(
            {
                "position": item.position,
                "title": item.title,
                "channel": item.channel_title,
                "duration_seconds": item.duration_seconds,
                "duration_iso": item.duration_iso,
                "video_id": item.video_id,
                "playlist_item_id": item.id,
                "privacy_status": item.privacy_status,
                "published_at": item.published_at.isoformat() if item.published_at else None,
            }
        )
    return rows


def export_playlist_json(
    playlist_id: str,
    *,
    title: str = "",
    out_dir: Optional[Path] = None,
    client: Optional[YouTubeClient] = None,
) -> Path:
    """
    PURPOSE:
        Export one playlist to a structured JSON file.

    INTERNAL LOGIC:
        Enriches items; writes {id,title,items:[...]} under YTPM_EXPORT_DIR.

    EXAMPLE INVOCATION:
        export_playlist_json("PLxxx", title="Favorites")
    """
    yt = get_client(client)
    items = yt.enrich_items(yt.list_playlist_items(playlist_id))
    export_root = out_dir or get_settings().export_dir()
    export_root.mkdir(parents=True, exist_ok=True)
    stem = _safe_filename(title) if title else playlist_id
    path = export_root / f"{stem}__{playlist_id[-8:]}.json"
    payload = {
        "playlist_id": playlist_id,
        "title": title,
        "item_count": len(items),
        "items": items_to_export_dicts(items),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Exported %s items to %s", len(items), path)
    return path
