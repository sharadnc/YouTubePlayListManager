"""
PURPOSE:
    Thin YouTube Data API v3 wrapper with pagination and duration helpers.

INTERNAL LOGIC:
    Wraps playlists / playlistItems / videos list and mutate calls; batches video ids.

EXAMPLE INVOCATION:
    from ytpm.youtube_client import YouTubeClient
    client = YouTubeClient.from_auth()
    playlists = client.list_my_playlists()
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from googleapiclient.errors import HttpError

from ytpm.auth import get_youtube_service
from ytpm.errors import PlaylistOrderError, QuotaExceededError, is_manual_sort_required, is_quota_exceeded
from ytpm.errors import QUOTA_HELP
from ytpm.models import Playlist, PlaylistItem, VideoMeta
from ytpm.quota import add_units, cost_for_http_method
from ytpm.titles import normalize_title

logger = logging.getLogger(__name__)

_ISO_DUR = re.compile(
    r"^PT(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?$"
)

# Titles YouTube puts on playlist rows when the video is actually gone / blocked.
_PLACEHOLDER_TITLES: set[str] = {
    "deleted video",
    "[deleted video]",
    "private video",
    "[private video]",
    "unavailable video",
    "[unavailable video]",
}


def is_placeholder_title(title: str) -> bool:
    """
    PURPOSE:
        Detect YouTube's dummy playlist titles for unplayable videos.

    INTERNAL LOGIC:
        Case-insensitive exact match against known placeholders.

    EXAMPLE INVOCATION:
        is_placeholder_title("Deleted video")  # True
    """
    return (title or "").strip().lower() in _PLACEHOLDER_TITLES


def parse_iso8601_duration(value: str) -> int:
    """
    PURPOSE:
        Convert YouTube ISO-8601 duration (e.g. PT1H2M3S) to total seconds.

    INTERNAL LOGIC:
        Regex-extract H/M/S groups and sum.

    EXAMPLE INVOCATION:
        parse_iso8601_duration("PT1H2M10S")  # 3730
    """
    if not value:
        return 0
    match = _ISO_DUR.match(value)
    if not match:
        return 0
    hours = int(match.group("h") or 0)
    minutes = int(match.group("m") or 0)
    seconds = int(match.group("s") or 0)
    return hours * 3600 + minutes * 60 + seconds


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """
    PURPOSE:
        Parse YouTube RFC3339 timestamps into datetime.

    INTERNAL LOGIC:
        Replaces trailing Z with +00:00 for fromisoformat.

    EXAMPLE INVOCATION:
        _parse_dt("2020-01-01T00:00:00Z")
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Unparseable datetime: %s", value)
        return None


def count_position_moves(ordered_items: List[PlaylistItem]) -> int:
    """
    PURPOSE:
        Count how many playlistItems.update calls apply_item_order would make.

    INTERNAL LOGIC:
        Same shift-on-move simulation as apply_item_order, without API calls.

    EXAMPLE INVOCATION:
        n = count_position_moves(sorted_items)
    """
    live: List[PlaylistItem] = sorted(
        ordered_items, key=lambda item: (item.position, item.id)
    )
    moved = 0
    for index, item in enumerate(ordered_items):
        live_index = next(
            i for i, current in enumerate(live) if current.id == item.id
        )
        if live_index == index:
            continue
        live.pop(live_index)
        live.insert(index, item)
        moved += 1
    return moved


def _api_call_meta(request: Any, resp: Any) -> Tuple[str, str]:
    """
    PURPOSE:
        Derive YouTube Data API method name and resource id from a request.

    INTERNAL LOGIC:
        Path `/youtube/v3/playlistItems` + HTTP DELETE → `playlistItems.delete`.
        Id from query, JSON body, or response.

    EXAMPLE INVOCATION:
        _api_call_meta(request, resp)  # ("playlistItems.update", "UExxx")
    """
    uri = str(getattr(request, "uri", "") or "")
    http = str(getattr(request, "method", "GET") or "GET").upper()
    parsed = urlparse(uri)
    resource = parsed.path.rstrip("/").rsplit("/", 1)[-1] or "unknown"
    verbs = {
        "GET": "list",
        "POST": "insert",
        "PUT": "update",
        "PATCH": "update",
        "DELETE": "delete",
    }
    method = f"{resource}.{verbs.get(http, http.lower())}"
    rid = ""
    qs = parse_qs(parsed.query)
    if qs.get("id"):
        rid = str(qs["id"][0])
    if not rid:
        body = getattr(request, "body", None)
        payload: Any = None
        if isinstance(body, bytes):
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
                payload = None
        elif isinstance(body, str):
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
        elif isinstance(body, dict):
            payload = body
        if isinstance(payload, dict) and payload.get("id"):
            rid = str(payload.get("id") or "")
    if not rid and isinstance(resp, dict) and resp.get("id"):
        rid = str(resp.get("id") or "")
    return method, rid


def _execute(request: Any) -> Any:
    """
    PURPOSE:
        Execute a Google API request and map daily quota errors.

    INTERNAL LOGIC:
        request.execute(); raises QuotaExceededError when the 10k pool is empty.
        Records units + method/id on the local ledger for writes.

    EXAMPLE INVOCATION:
        resp = _execute(service.playlists().list(part="id", mine=True))
    """
    try:
        resp = request.execute()
    except HttpError as exc:
        if is_quota_exceeded(exc):
            raise QuotaExceededError(QUOTA_HELP) from exc
        raise
    units, is_write = cost_for_http_method(str(getattr(request, "method", "GET")))
    method, resource_id = _api_call_meta(request, resp)
    add_units(units, is_write=is_write, method=method, resource_id=resource_id)
    return resp


class YouTubeClient:
    """
    PURPOSE:
        High-level YouTube playlist/item operations with pagination.

    INTERNAL LOGIC:
        Holds discovery service; exposes list/create/update/delete helpers.

    EXAMPLE INVOCATION:
        yt = YouTubeClient.from_auth()
        for pl in yt.list_my_playlists():
            print(pl.title)
    """

    def __init__(self, service: Any) -> None:
        """
        PURPOSE:
            Wrap an existing youtube discovery resource.

        INTERNAL LOGIC:
            Stores service reference for subsequent API calls.

        EXAMPLE INVOCATION:
            YouTubeClient(get_youtube_service())
        """
        self._yt = service

    @classmethod
    def from_auth(cls) -> "YouTubeClient":
        """
        PURPOSE:
            Build client using cached OAuth credentials.

        INTERNAL LOGIC:
            Calls get_youtube_service().

        EXAMPLE INVOCATION:
            YouTubeClient.from_auth()
        """
        return cls(get_youtube_service())

    def list_my_playlists(self) -> List[Playlist]:
        """
        PURPOSE:
            Fetch all playlists owned by the authenticated channel.

        INTERNAL LOGIC:
            Paginates playlists.list(mine=True) with snippet + contentDetails + status.

        EXAMPLE INVOCATION:
            client.list_my_playlists()
        """
        results: List[Playlist] = []
        page_token: Optional[str] = None
        while True:
            resp = _execute(
                self._yt.playlists().list(
                    part="snippet,contentDetails,status",
                    mine=True,
                    maxResults=50,
                    pageToken=page_token,
                )
            )
            for item in resp.get("items", []):
                snippet = item.get("snippet", {})
                content = item.get("contentDetails", {})
                status = item.get("status", {})
                results.append(
                    Playlist(
                        id=item["id"],
                        title=snippet.get("title", ""),
                        description=snippet.get("description", "") or "",
                        item_count=int(content.get("itemCount", 0) or 0),
                        privacy=status.get("privacyStatus", "private"),
                        published_at=_parse_dt(snippet.get("publishedAt")),
                    )
                )
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return results

    def get_mine_channel_id(self) -> Optional[str]:
        """
        PURPOSE:
            Return the authenticated user's YouTube channel id.

        INTERNAL LOGIC:
            channels.list(mine=True); first item id.

        EXAMPLE INVOCATION:
            client.get_mine_channel_id()
        """
        resp = _execute(self._yt.channels().list(part="id", mine=True))
        items = resp.get("items") or []
        if not items:
            return None
        return str(items[0].get("id") or "") or None

    def _video_snippet_title_body(self, item: Dict[str, Any], new_title: str) -> Dict[str, Any]:
        """
        PURPOSE:
            Build a videos.update snippet body that keeps category, description, tags.

        INTERNAL LOGIC:
            YouTube requires categoryId on snippet updates; default 22 (People & Blogs).

        EXAMPLE INVOCATION:
            body = client._video_snippet_title_body(item, "New title")
        """
        sn = item.get("snippet", {})
        body: Dict[str, Any] = {
            "id": item["id"],
            "snippet": {
                "title": new_title,
                "categoryId": str(sn.get("categoryId") or "22"),
                "description": sn.get("description") or "",
            },
        }
        tags = sn.get("tags")
        if tags:
            body["snippet"]["tags"] = tags
        return body

    def update_owned_video_title(self, video_id: str, new_title: str) -> str:
        """
        PURPOSE:
            Rename a video the authenticated user uploaded (not a playlist-only label).

        INTERNAL LOGIC:
            videos.list snippet; reject other channels; videos.update if the title changed.

        EXAMPLE INVOCATION:
            client.update_owned_video_title("dQw4", "New title")
        """
        title = (new_title or "").strip()
        if not title:
            raise ValueError("Title cannot be empty.")
        vid = (video_id or "").strip()
        if not vid:
            raise ValueError("Video id is required.")
        owner = self.get_mine_channel_id()
        if not owner:
            raise PermissionError("Could not resolve your YouTube channel.")
        resp = _execute(self._yt.videos().list(part="snippet", id=vid))
        found = resp.get("items") or []
        if not found:
            raise ValueError(f"Video not found: {vid}")
        item = found[0]
        sn = item.get("snippet", {})
        if sn.get("channelId") != owner:
            raise PermissionError(
                "You can only rename videos you uploaded. "
                "Playlist rows use the video's real title; other channels cannot be renamed."
            )
        old_title = sn.get("title") or ""
        if title == old_title:
            return title
        _execute(
            self._yt.videos().update(
                part="snippet", body=self._video_snippet_title_body(item, title)
            )
        )
        logger.info("Renamed video %s to %s", vid, title)
        return title

    def collapse_owned_video_titles(self, video_ids: List[str]) -> int:
        """
        PURPOSE:
            Collapse consecutive spaces in titles of videos the user owns.

        INTERNAL LOGIC:
            No-op when video_ids is empty. videos.list snippet; if channelId
            matches mine and normalize_title actually changes the title,
            videos.update snippet (keeps categoryId/description).

        EXAMPLE INVOCATION:
            n = client.collapse_owned_video_titles(["abc", "def"])
        """
        unique = [vid for vid in dict.fromkeys(video_ids) if vid]
        if not unique:
            return 0
        owner = self.get_mine_channel_id()
        if not owner:
            return 0
        updated = 0
        for i in range(0, len(unique), 50):
            chunk = unique[i : i + 50]
            try:
                resp = _execute(
                    self._yt.videos().list(part="snippet", id=",".join(chunk))
                )
            except HttpError as exc:
                if is_quota_exceeded(exc):
                    raise QuotaExceededError(QUOTA_HELP) from exc
                raise
            for item in resp.get("items", []):
                sn = item.get("snippet", {})
                if sn.get("channelId") != owner:
                    continue
                old_title = sn.get("title") or ""
                new_title = normalize_title(old_title)
                if new_title == old_title or not new_title:
                    continue
                body = self._video_snippet_title_body(item, new_title)
                try:
                    _execute(self._yt.videos().update(part="snippet", body=body))
                    updated += 1
                    logger.info("Collapsed spaces in title for video %s", item["id"])
                except HttpError as exc:
                    if is_quota_exceeded(exc):
                        raise QuotaExceededError(QUOTA_HELP) from exc
                    logger.warning("Could not update title for %s: %s", item["id"], exc)
        return updated

    def create_playlist(
        self,
        title: str,
        *,
        description: str = "",
        privacy: str = "private",
    ) -> Playlist:
        """
        PURPOSE:
            Create a new playlist on the authenticated channel.

        INTERNAL LOGIC:
            playlists.insert with snippet + status.

        EXAMPLE INVOCATION:
            client.create_playlist("New Mix", privacy="private")
        """
        body = {
            "snippet": {"title": title, "description": description},
            "status": {"privacyStatus": privacy},
        }
        try:
            resp = _execute(
                self._yt.playlists().insert(
                    part="snippet,status,contentDetails", body=body
                )
            )
        except HttpError as exc:
            if is_quota_exceeded(exc):
                raise QuotaExceededError(QUOTA_HELP) from exc
            raise
        snippet = resp.get("snippet", {})
        status = resp.get("status", {})
        content = resp.get("contentDetails", {})
        return Playlist(
            id=resp["id"],
            title=snippet.get("title", title),
            description=snippet.get("description", "") or "",
            item_count=int(content.get("itemCount", 0) or 0),
            privacy=status.get("privacyStatus", privacy),
            published_at=_parse_dt(snippet.get("publishedAt")),
        )

    def rename_playlist(self, playlist_id: str, new_title: str) -> Playlist:
        """
        PURPOSE:
            Rename an existing playlist.

        INTERNAL LOGIC:
            playlists.update with snippet title (keeps description if present).

        EXAMPLE INVOCATION:
            client.rename_playlist("PLxxx", "Renamed")
        """
        existing = _execute(
            self._yt.playlists().list(
                part="snippet,status,contentDetails", id=playlist_id
            )
        )
        items = existing.get("items", [])
        if not items:
            raise ValueError(f"Playlist not found: {playlist_id}")
        item = items[0]
        snippet = item.get("snippet", {})
        body = {
            "id": playlist_id,
            "snippet": {
                "title": new_title,
                "description": snippet.get("description", "") or "",
            },
            "status": {"privacyStatus": item.get("status", {}).get("privacyStatus", "private")},
        }
        resp = _execute(
            self._yt.playlists().update(part="snippet,status", body=body)
        )
        sn = resp.get("snippet", {})
        st = resp.get("status", {})
        return Playlist(
            id=resp["id"],
            title=sn.get("title", new_title),
            description=sn.get("description", "") or "",
            item_count=int(item.get("contentDetails", {}).get("itemCount", 0) or 0),
            privacy=st.get("privacyStatus", "private"),
            published_at=_parse_dt(sn.get("publishedAt")),
        )

    def set_playlist_description(self, playlist_id: str, description: str) -> Playlist:
        """
        PURPOSE:
            Update a playlist's description (keeps title and privacy).

        INTERNAL LOGIC:
            playlists.list then playlists.update snippet. Unchanged text skips
            the write (list still costs 1 unit).

        EXAMPLE INVOCATION:
            client.set_playlist_description("PLxxx", "Year mix")
        """
        existing = _execute(
            self._yt.playlists().list(
                part="snippet,status,contentDetails", id=playlist_id
            )
        )
        items = existing.get("items", [])
        if not items:
            raise ValueError(f"Playlist not found: {playlist_id}")
        item = items[0]
        snippet = item.get("snippet", {})
        current = snippet.get("description", "") or ""
        if current == description:
            return Playlist(
                id=playlist_id,
                title=snippet.get("title") or "",
                description=current,
                item_count=int(item.get("contentDetails", {}).get("itemCount", 0) or 0),
                privacy=item.get("status", {}).get("privacyStatus", "private"),
                published_at=_parse_dt(snippet.get("publishedAt")),
            )
        body = {
            "id": playlist_id,
            "snippet": {
                "title": snippet.get("title") or "Untitled",
                "description": description,
            },
            "status": {
                "privacyStatus": item.get("status", {}).get("privacyStatus", "private")
            },
        }
        resp = _execute(
            self._yt.playlists().update(part="snippet,status", body=body)
        )
        sn = resp.get("snippet", {})
        st = resp.get("status", {})
        return Playlist(
            id=resp["id"],
            title=sn.get("title", snippet.get("title", "")),
            description=sn.get("description", "") or "",
            item_count=int(item.get("contentDetails", {}).get("itemCount", 0) or 0),
            privacy=st.get("privacyStatus", "private"),
            published_at=_parse_dt(sn.get("publishedAt")),
        )

    def set_playlist_privacy(self, playlist_id: str, privacy: str) -> Playlist:
        """
        PURPOSE:
            Set playlist privacy to public, unlisted, or private.

        INTERNAL LOGIC:
            playlists.list then playlists.update status.privacyStatus.

        EXAMPLE INVOCATION:
            client.set_playlist_privacy("PLxxx", "unlisted")
        """
        allowed = {"public", "unlisted", "private"}
        if privacy not in allowed:
            raise ValueError(f"privacy must be one of {sorted(allowed)}")
        existing = _execute(
            self._yt.playlists().list(
                part="snippet,status,contentDetails", id=playlist_id
            )
        )
        items = existing.get("items", [])
        if not items:
            raise ValueError(f"Playlist not found: {playlist_id}")
        item = items[0]
        snippet = item.get("snippet", {})
        body = {
            "id": playlist_id,
            "snippet": {
                "title": snippet.get("title") or "Untitled",
                "description": snippet.get("description", "") or "",
            },
            "status": {"privacyStatus": privacy},
        }
        resp = _execute(
            self._yt.playlists().update(part="snippet,status", body=body)
        )
        sn = resp.get("snippet", {})
        st = resp.get("status", {})
        return Playlist(
            id=resp["id"],
            title=sn.get("title", snippet.get("title", "")),
            description=sn.get("description", "") or "",
            item_count=int(item.get("contentDetails", {}).get("itemCount", 0) or 0),
            privacy=st.get("privacyStatus", privacy),
            published_at=_parse_dt(sn.get("publishedAt")),
        )

    def delete_playlist(self, playlist_id: str) -> None:
        """
        PURPOSE:
            Permanently delete a playlist.

        INTERNAL LOGIC:
            playlists.delete.

        EXAMPLE INVOCATION:
            client.delete_playlist("PLxxx")
        """
        _execute(self._yt.playlists().delete(id=playlist_id))

    def list_playlist_items(self, playlist_id: str) -> List[PlaylistItem]:
        """
        PURPOSE:
            Fetch all items in a playlist in position order.

        INTERNAL LOGIC:
            Paginates playlistItems.list; maps snippet + contentDetails + status.

        EXAMPLE INVOCATION:
            client.list_playlist_items("PLxxx")
        """
        results: List[PlaylistItem] = []
        page_token: Optional[str] = None
        while True:
            resp = _execute(
                self._yt.playlistItems().list(
                    part="snippet,contentDetails,status",
                    playlistId=playlist_id,
                    maxResults=50,
                    pageToken=page_token,
                )
            )
            for item in resp.get("items", []):
                snippet = item.get("snippet", {})
                resource = snippet.get("resourceId", {})
                status = item.get("status", {})
                results.append(
                    PlaylistItem(
                        id=item["id"],
                        video_id=resource.get("videoId", "")
                        or item.get("contentDetails", {}).get("videoId", ""),
                        title=snippet.get("title", "") or "",
                        channel_title=snippet.get("videoOwnerChannelTitle", "")
                        or snippet.get("channelTitle", "")
                        or "",
                        position=int(snippet.get("position", 0) or 0),
                        published_at=_parse_dt(snippet.get("publishedAt")),
                        privacy_status=status.get("privacyStatus", "public") or "public",
                    )
                )
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        results.sort(key=lambda x: x.position)
        return results

    def insert_video(
        self,
        playlist_id: str,
        video_id: str,
        *,
        position: Optional[int] = None,
    ) -> PlaylistItem:
        """
        PURPOSE:
            Add a video to a playlist (optionally at a position).

        INTERNAL LOGIC:
            playlistItems.insert with resourceId videoId.

        EXAMPLE INVOCATION:
            client.insert_video("PLxxx", "dQw4w9WgXcQ", position=0)
        """
        body: Dict[str, Any] = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        }
        if position is not None:
            body["snippet"]["position"] = position
        try:
            resp = _execute(
                self._yt.playlistItems().insert(part="snippet", body=body)
            )
        except HttpError as exc:
            if is_quota_exceeded(exc):
                raise QuotaExceededError(QUOTA_HELP) from exc
            raise
        snippet = resp.get("snippet", {})
        return PlaylistItem(
            id=resp["id"],
            video_id=video_id,
            title=snippet.get("title", "") or "",
            channel_title=snippet.get("videoOwnerChannelTitle", "") or "",
            position=int(snippet.get("position", 0) or 0),
            published_at=_parse_dt(snippet.get("publishedAt")),
        )

    def delete_playlist_item(self, playlist_item_id: str) -> None:
        """
        PURPOSE:
            Remove one playlist item by its playlistItem id.

        INTERNAL LOGIC:
            playlistItems.delete.

        EXAMPLE INVOCATION:
            client.delete_playlist_item("UExxx")
        """
        try:
            _execute(self._yt.playlistItems().delete(id=playlist_item_id))
        except HttpError as exc:
            if is_quota_exceeded(exc):
                raise QuotaExceededError(QUOTA_HELP) from exc
            raise

    def update_item_position(self, item: PlaylistItem, playlist_id: str, position: int) -> None:
        """
        PURPOSE:
            Move an existing playlist item to a new zero-based position.

        INTERNAL LOGIC:
            playlistItems.update with snippet.position and resourceId.

        EXAMPLE INVOCATION:
            client.update_item_position(item, "PLxxx", 2)
        """
        body = {
            "id": item.id,
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": item.video_id},
                "position": position,
            },
        }
        try:
            _execute(self._yt.playlistItems().update(part="snippet", body=body))
        except HttpError as exc:
            if is_quota_exceeded(exc):
                raise QuotaExceededError(QUOTA_HELP) from exc
            raise

    def copy_playlist_in_order(
        self,
        source_title: str,
        video_ids: List[str],
        *,
        suffix: str = " (sorted)",
    ) -> Playlist:
        """
        PURPOSE:
            Create a new playlist and append videos in the given order (no position field).

        INTERNAL LOGIC:
            Leaves the original playlist untouched. New playlists typically accept
            append order. Costs ~50 quota units per video plus 50 to create.

        EXAMPLE INVOCATION:
            client.copy_playlist_in_order("2026", ["aaa", "bbb"])
        """
        title = f"{source_title}{suffix}"[:140]
        created = self.create_playlist(title, description=f"Sorted copy of {source_title}")
        logger.info("Created sorted copy %s (%s)", created.title, created.id)
        ids = [vid for vid in video_ids if vid]
        try:
            for video_id in ids:
                try:
                    self.insert_video(created.id, video_id)
                except HttpError as exc:
                    if is_quota_exceeded(exc):
                        raise QuotaExceededError(
                            f"{QUOTA_HELP}\n\nOriginal playlist unchanged. "
                            f"Incomplete copy may exist as: {created.title}"
                        ) from exc
                    logger.warning("Could not add %s to copy %s: %s", video_id, created.id, exc)
            live = [item.video_id for item in self.list_playlist_items(created.id)]
            if live == ids:
                return created
            if ids and live == list(reversed(ids)):
                logger.info("Copy %s is newest-first; inserting in reverse", created.id)
                self._clear_playlist_items(created.id)
                for video_id in reversed(ids):
                    self.insert_video(created.id, video_id)
            return created
        except QuotaExceededError:
            raise

    def _clear_playlist_items(self, playlist_id: str) -> None:
        """
        PURPOSE:
            Delete every playlistItem in a playlist (videos stay on YouTube).

        INTERNAL LOGIC:
            Lists items then playlistItems.delete each id.

        EXAMPLE INVOCATION:
            client._clear_playlist_items("PLxxx")
        """
        for item in self.list_playlist_items(playlist_id):
            self.delete_playlist_item(item.id)

    def _append_videos(self, playlist_id: str, video_ids: List[str]) -> None:
        """
        PURPOSE:
            Append videos in sequence without setting snippet.position.

        INTERNAL LOGIC:
            Inserts each video_id with no position so auto-sorted playlists accept it.

        EXAMPLE INVOCATION:
            client._append_videos("PLxxx", ["abc", "def"])
        """
        for video_id in video_ids:
            self.insert_video(playlist_id, video_id)

    def rebuild_playlist_order(self, playlist_id: str, video_ids: List[str]) -> None:
        """
        PURPOSE:
            Force a playlist into a given video order without using position updates.

        INTERNAL LOGIC:
            YouTube rejects snippet.position unless Sort is Manual (Studio-only).
            Workaround: delete all items and re-add without position. Date-added
            auto-sort follows insert time; if the live order is reversed, insert
            again in reverse. Popularity/publish-date auto-sort cannot stick.

        EXAMPLE INVOCATION:
            client.rebuild_playlist_order("PLxxx", ["vid1", "vid2"])
        """
        studio = f"https://studio.youtube.com/playlist/{playlist_id}/videos"
        desired = list(video_ids)
        logger.info("Rebuilding playlist %s order (%s videos, no position field)", playlist_id, len(desired))
        self._clear_playlist_items(playlist_id)
        self._append_videos(playlist_id, desired)
        live = [item.video_id for item in self.list_playlist_items(playlist_id)]
        if live == desired:
            logger.info("Rebuild matched desired order for %s", playlist_id)
            return
        if live == list(reversed(desired)):
            logger.info("Playlist %s is newest-first; inserting in reverse", playlist_id)
            self._clear_playlist_items(playlist_id)
            self._append_videos(playlist_id, list(reversed(desired)))
            live = [item.video_id for item in self.list_playlist_items(playlist_id)]
            if live == desired:
                logger.info("Reverse rebuild matched desired order for %s", playlist_id)
                return
        raise PlaylistOrderError(
            "YouTube is auto-sorting this playlist (popularity or publish date), "
            "so a custom order cannot stick.\n\n"
            "Open YouTube Studio → this playlist → Sort → Manual, then retry:\n"
            f"{studio}"
        )

    def apply_item_order(
        self,
        playlist_id: str,
        ordered_items: List[PlaylistItem],
        *,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        """
        PURPOSE:
            Apply an in-memory item order using playlistItems.update positions.

        INTERNAL LOGIC:
            Updates only items that are not already at the target index,
            simulating YouTube's shift-on-move so later skips stay correct.

        EXAMPLE INVOCATION:
            moved = client.apply_item_order("PLxxx", sorted_items)
        """
        studio = f"https://studio.youtube.com/playlist/{playlist_id}/videos"
        planned = count_position_moves(ordered_items)
        if on_progress:
            on_progress(0, planned)
        live: List[PlaylistItem] = sorted(
            ordered_items, key=lambda item: (item.position, item.id)
        )
        moved = 0
        try:
            for index, item in enumerate(ordered_items):
                live_index = next(
                    i for i, current in enumerate(live) if current.id == item.id
                )
                if live_index == index:
                    continue
                self.update_item_position(item, playlist_id, index)
                live.pop(live_index)
                live.insert(index, item)
                item.position = index
                moved += 1
                if on_progress:
                    on_progress(moved, planned)
        except HttpError as exc:
            if is_quota_exceeded(exc):
                raise QuotaExceededError(QUOTA_HELP) from exc
            if is_manual_sort_required(exc):
                raise PlaylistOrderError(
                    "This playlist is not set to Manual sort, so YouTube blocks position updates.\n\n"
                    "Set Sort → Manual in YouTube Studio and retry:\n"
                    f"{studio}"
                ) from exc
            logger.exception("Failed to update playlist item positions")
            raise
        return moved

    def get_videos_meta(self, video_ids: Iterable[str]) -> Dict[str, VideoMeta]:
        """
        PURPOSE:
            Batch-fetch video metadata (duration, privacy, channel).

        INTERNAL LOGIC:
            Chunks ids by 50; videos.list; marks missing ids as exists=False.

        EXAMPLE INVOCATION:
            client.get_videos_meta(["abc", "def"])
        """
        ids = [v for v in dict.fromkeys(video_ids) if v]
        found: Dict[str, VideoMeta] = {}
        for i in range(0, len(ids), 50):
            chunk = ids[i : i + 50]
            resp = _execute(
                self._yt.videos().list(
                    part="snippet,contentDetails,status", id=",".join(chunk)
                )
            )
            for item in resp.get("items", []):
                sn = item.get("snippet", {})
                cd = item.get("contentDetails", {})
                st = item.get("status", {})
                dur = cd.get("duration", "") or ""
                found[item["id"]] = VideoMeta(
                    video_id=item["id"],
                    title=sn.get("title", "") or "",
                    channel_title=sn.get("channelTitle", "") or "",
                    duration_iso=dur,
                    duration_seconds=parse_iso8601_duration(dur),
                    privacy_status=st.get("privacyStatus", "public") or "public",
                    exists=True,
                )
        for vid in ids:
            if vid not in found:
                found[vid] = VideoMeta(video_id=vid, exists=False, privacy_status="deleted")
        return found

    def enrich_items(self, items: List[PlaylistItem]) -> List[PlaylistItem]:
        """
        PURPOSE:
            Attach duration and privacy from videos.list onto playlist items.

        INTERNAL LOGIC:
            Batch get_videos_meta; mutate copies of PlaylistItem fields.

        EXAMPLE INVOCATION:
            enriched = client.enrich_items(items)
        """
        meta = self.get_videos_meta([i.video_id for i in items])
        enriched: List[PlaylistItem] = []
        for item in items:
            m = meta.get(item.video_id)
            data = item.model_dump()
            if m:
                if not m.exists:
                    # videos.list often omits unlisted videos you can still play
                    # in the playlist. Only treat as deleted when YouTube itself
                    # replaced the title with a placeholder.
                    if is_placeholder_title(item.title) or not (item.title or "").strip():
                        data["privacy_status"] = "deleted"
                        data["title"] = item.title.strip() or "[Deleted video]"
                else:
                    data["duration_iso"] = m.duration_iso
                    data["duration_seconds"] = m.duration_seconds
                    data["privacy_status"] = m.privacy_status
                    if m.channel_title:
                        data["channel_title"] = m.channel_title
                    if m.title and (not item.title or item.title in ("Private video", "Deleted video")):
                        data["title"] = m.title
            enriched.append(PlaylistItem(**data))
        return enriched
