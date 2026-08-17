"""
PURPOSE:
    Sort playlist items by title, date, duration, or channel and rewrite remote order.

INTERNAL LOGIC:
    1. Sort in memory and save list-mode file (no write quota).
    2. Title and date sorts both collapse extra spaces, delete duplicates,
       then write only items whose position actually changed (Manual sort).
    3. If YouTube requires Manual sort, copy into a NEW playlist instead of
       deleting/re-adding (original stays intact; ~50 units/video).
    4. On quota errors, stop immediately and point at the saved list-mode file.

EXAMPLE INVOCATION:
    from ytpm.ops.sort import sort_playlist
    sort_playlist("PLxxx", by="title")
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Callable, List, Literal, Optional, Union

from ytpm.errors import PlaylistOrderError, QuotaExceededError
from ytpm.jobs import enqueue_sorts, mark_sort_done
from ytpm.list_mode import snapshot_playlist, write_sorted_list_file
from ytpm.models import PlaylistItem
from ytpm.quota import WRITE_UNITS, remaining_units
from ytpm.titles import normalize_title, title_needs_space_collapse
from ytpm.ops.playlists import get_client
from ytpm.youtube_client import YouTubeClient, count_position_moves, is_placeholder_title

logger = logging.getLogger(__name__)

SortBy = Literal["title", "date", "duration", "channel"]


def _sort_key_title(item: PlaylistItem) -> str:
    """
    PURPOSE:
        Case-insensitive title sort key with consecutive spaces collapsed.

    INTERNAL LOGIC:
        normalize_title then lowercase.

    EXAMPLE INVOCATION:
        sorted(items, key=_sort_key_title)
    """
    return normalize_title(item.title).lower()


def _sort_key_date(item: PlaylistItem) -> datetime:
    """
    PURPOSE:
        Date-added sort key (playlistItem publishedAt).

    INTERNAL LOGIC:
        Missing dates sort as datetime.min UTC.

    EXAMPLE INVOCATION:
        sorted(items, key=_sort_key_date)
    """
    if item.published_at is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return item.published_at


def _sort_key_duration(item: PlaylistItem) -> int:
    """
    PURPOSE:
        Duration sort key in seconds.

    INTERNAL LOGIC:
        Missing duration sorts as 0.

    EXAMPLE INVOCATION:
        sorted(items, key=_sort_key_duration)
    """
    return int(item.duration_seconds or 0)


def _sort_key_channel(item: PlaylistItem) -> str:
    """
    PURPOSE:
        Case-insensitive channel name sort key.

    INTERNAL LOGIC:
        Lowercases channel_title.

    EXAMPLE INVOCATION:
        sorted(items, key=_sort_key_channel)
    """
    return (item.channel_title or "").lower()


KeepKey = Callable[[PlaylistItem], Union[str, datetime]]


def keep_key_for(by: SortBy) -> KeepKey:
    """
    PURPOSE:
        Map a sort mode to its item key function.

    INTERNAL LOGIC:
        title/date/duration/channel lookup.

    EXAMPLE INVOCATION:
        keep_key_for("duration")
    """
    keys: dict[str, KeepKey] = {
        "title": _sort_key_title,
        "date": _sort_key_date,
        "duration": _sort_key_duration,
        "channel": _sort_key_channel,
    }
    if by not in keys:
        raise ValueError(f"Unsupported sort key: {by}")
    return keys[by]


def sort_suffix(by: SortBy, reverse: bool) -> str:
    """
    PURPOSE:
        Playlist copy title suffix for a sort mode.

    INTERNAL LOGIC:
        Human-readable direction label.

    EXAMPLE INVOCATION:
        sort_suffix("title", False)  # " (A-Z)"
    """
    labels = {
        ("title", False): " (A-Z)",
        ("title", True): " (Z-A)",
        ("date", False): " (oldest first)",
        ("date", True): " (newest first)",
        ("duration", False): " (shortest first)",
        ("duration", True): " (longest first)",
        ("channel", False): " (channel A-Z)",
        ("channel", True): " (channel Z-A)",
    }
    return labels.get((by, reverse), " (sorted)")


@dataclass
class SortPlan:
    """
    PURPOSE:
        In-memory sort result used for dry-run estimates and live writes.

    INTERNAL LOGIC:
        Holds ordered kept items, collapse ids, dropped rows, move count.

    EXAMPLE INVOCATION:
        plan = plan_sort(items, by="title")
    """

    ordered: List[PlaylistItem]
    collapse_ids: List[str]
    dropped: List[PlaylistItem]
    move_count: int
    suffix: str
    by: SortBy

    @property
    def write_ops(self) -> int:
        """Estimated write calls (title updates + deletes + moves)."""
        return len(self.collapse_ids) + len(self.dropped) + self.move_count

    @property
    def units(self) -> int:
        """Estimated quota units for writes only."""
        return self.write_ops * WRITE_UNITS

    def summary(self, title: str) -> str:
        """
        PURPOSE:
            Human-readable dry-run report.

        INTERNAL LOGIC:
            Counts collapse/dupe/move; lists a few dropped titles.

        EXAMPLE INVOCATION:
            plan.summary("2024")
        """
        drops = ", ".join(item.title[:40] for item in self.dropped[:8])
        extra = f"\nDuplicates to remove: {drops}" if drops else ""
        more = "" if len(self.dropped) <= 8 else f" (+{len(self.dropped) - 8} more)"
        return (
            f'Dry run "{title}" by {self.by}:\n'
            f"- Collapse extra spaces: {len(self.collapse_ids)} owned title(s)\n"
            f"- Remove duplicates: {len(self.dropped)}\n"
            f"- Move items: {self.move_count}\n"
            f"- Estimated writes: {self.write_ops} (~{self.units:,} units)"
            f"{extra}{more}"
        )


def dedupe_after_title_normalize(
    items: List[PlaylistItem],
    *,
    keep_key: Optional[KeepKey] = None,
) -> tuple[List[PlaylistItem], List[PlaylistItem]]:
    """
    PURPOSE:
        Keep first item per video id and per normalized title (after space collapse).

    INTERNAL LOGIC:
        Walks items sorted by keep_key (title by default, date for date-sort);
        drops later same video_id or same collapsed title. Placeholder titles
        (Deleted video / Private video) are not merged with each other.

    EXAMPLE INVOCATION:
        kept, dropped = dedupe_after_title_normalize(items, keep_key=_sort_key_date)
    """
    ordered = sorted(items, key=keep_key or _sort_key_title)
    kept: List[PlaylistItem] = []
    dropped: List[PlaylistItem] = []
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    for item in ordered:
        vid = (item.video_id or "").strip()
        collapsed = normalize_title(item.title)
        title_key = collapsed.lower()
        if vid and vid in seen_ids:
            dropped.append(item)
            continue
        placeholder = is_placeholder_title(item.title)
        if title_key and not placeholder and title_key in seen_titles:
            dropped.append(item)
            continue
        if vid:
            seen_ids.add(vid)
        if title_key and not placeholder:
            seen_titles.add(title_key)
        if collapsed != item.title:
            item = item.model_copy(update={"title": collapsed})
        kept.append(item)
    return kept, dropped


def plan_sort(
    items: List[PlaylistItem],
    by: SortBy,
    *,
    reverse: bool = False,
) -> SortPlan:
    """
    PURPOSE:
        Compute collapse/dedupe/order in memory (no YouTube writes).

    INTERNAL LOGIC:
        Same keep_key as live sort; count_position_moves for move estimate.

    EXAMPLE INVOCATION:
        plan = plan_sort(items, by="duration")
    """
    keep_key = keep_key_for(by)
    collapse_ids = _video_ids_needing_title_collapse(items)
    kept, dropped = dedupe_after_title_normalize(items, keep_key=keep_key)
    ordered = sorted(kept, key=keep_key, reverse=reverse)
    return SortPlan(
        ordered=ordered,
        collapse_ids=collapse_ids,
        dropped=dropped,
        move_count=count_position_moves(ordered),
        suffix=sort_suffix(by, reverse),
        by=by,
    )


def _playlist_title(yt: YouTubeClient, playlist_id: str) -> str:
    """
    PURPOSE:
        Resolve a playlist id to its current title.

    INTERNAL LOGIC:
        Scans list_my_playlists; falls back to the id.

    EXAMPLE INVOCATION:
        _playlist_title(yt, "PLxxx")
    """
    for pl in yt.list_my_playlists():
        if pl.id == playlist_id:
            return pl.title
    return playlist_id


def _video_ids_needing_title_collapse(items: List[PlaylistItem]) -> List[str]:
    """
    PURPOSE:
        Collect unique video ids whose playlist titles still have extra whitespace.

    INTERNAL LOGIC:
        First occurrence of each video_id whose title_needs_space_collapse is True.

    EXAMPLE INVOCATION:
        ids = _video_ids_needing_title_collapse(items)
    """
    seen: set[str] = set()
    needed: List[str] = []
    for item in items:
        vid = (item.video_id or "").strip()
        if not vid or vid in seen:
            continue
        if not title_needs_space_collapse(item.title):
            continue
        seen.add(vid)
        needed.append(vid)
    return needed


def _refresh_kept_from_live(
    live_items: List[PlaylistItem],
    kept: List[PlaylistItem],
) -> List[PlaylistItem]:
    """
    PURPOSE:
        Replace kept rows with live playlist items so positions match YouTube.

    INTERNAL LOGIC:
        Maps live items by playlistItem id; drops kept rows that were deleted.

    EXAMPLE INVOCATION:
        kept = _refresh_kept_from_live(yt.list_playlist_items(pid), kept)
    """
    live_by_id = {item.id: item for item in live_items}
    return [live_by_id[item.id] for item in kept if item.id in live_by_id]


def sort_playlist(
    playlist_id: str,
    by: SortBy = "title",
    *,
    reverse: bool = False,
    dry_run: bool = False,
    title: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    client: Optional[YouTubeClient] = None,
) -> str:
    """
    PURPOSE:
        Reorder a playlist (quota-safe) with optional dry-run.

    INTERNAL LOGIC:
        Snapshots live order, saves intended list-mode file, then writes only
        collapsed titles, duplicate deletes, and moved items. Dry-run stops
        after the local file (0 writes).

    EXAMPLE INVOCATION:
        sort_playlist("PLxxx", by="duration", dry_run=True)
    """
    yt = get_client(client)
    items = yt.list_playlist_items(playlist_id)
    if by in ("duration", "channel"):
        items = yt.enrich_items(items)
    keep_key = keep_key_for(by)
    plan = plan_sort(items, by, reverse=reverse)
    display = title or _playlist_title(yt, playlist_id)
    snapshot_playlist(playlist_id, display, items)
    saved = write_sorted_list_file(playlist_id, display, plan.ordered)
    if dry_run:
        return f"{plan.summary(display)}\n\nIntended order saved to:\n{saved}"
    titles_fixed = 0
    dropped_n = len(plan.dropped)
    ordered = plan.ordered
    try:
        titles_fixed = (
            yt.collapse_owned_video_titles(plan.collapse_ids)
            if plan.collapse_ids
            else 0
        )
        for extra in plan.dropped:
            yt.delete_playlist_item(extra.id)
        if plan.dropped:
            kept = _refresh_kept_from_live(
                yt.list_playlist_items(playlist_id),
                ordered,
            )
            ordered = sorted(kept, key=keep_key, reverse=reverse)
        moved_n = yt.apply_item_order(
            playlist_id, ordered, on_progress=on_progress
        )
        extra = (
            f" Collapsed {titles_fixed} title(s); removed {dropped_n} "
            f"duplicate(s); moved {moved_n} item(s)."
        )
        logger.info(
            "Sorted playlist %s in place by %s (%s items, moved %s)",
            playlist_id,
            by,
            len(ordered),
            moved_n,
        )
        return f'Sorted "{display}" in place by {by} ({len(ordered)} videos).{extra}'
    except PlaylistOrderError:
        copy = yt.copy_playlist_in_order(
            display,
            [item.video_id for item in ordered],
            suffix=plan.suffix,
        )
        return (
            f'YouTube blocked in-place sort on "{display}" (Sort is not Manual).\n\n'
            f'Created a new playlist instead: "{copy.title}"\n'
            f"Removed {dropped_n} duplicate(s) from the original; "
            f"collapsed {titles_fixed} owned title(s).\n"
            f"The original playlist was not reordered.\n\n"
            f"Intended order also saved to:\n{saved}"
        )
    except QuotaExceededError as exc:
        raise QuotaExceededError(
            f"{exc}\n\nIntended order saved to:\n{saved}\n"
            "Use Resume unfinished sorts or List Mode: Apply after quota resets."
        ) from exc


def sort_many(
    playlist_ids: List[str],
    by: SortBy = "title",
    *,
    reverse: bool = False,
    dry_run: bool = False,
    titles: Optional[dict[str, str]] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    client: Optional[YouTubeClient] = None,
) -> str:
    """
    PURPOSE:
        Sort multiple playlists; stop when estimated remaining quota is too low.

    INTERNAL LOGIC:
        Enqueues jobs; skips further writes when remaining_units < 50.

    EXAMPLE INVOCATION:
        sort_many(["PLa", "PLb"], by="title")
    """
    yt = get_client(client)
    names = titles or {}
    if not dry_run:
        enqueue_sorts(playlist_ids, by=by, reverse=reverse, titles=names)
    notes: List[str] = []
    for pid in playlist_ids:
        if not dry_run and remaining_units() < WRITE_UNITS:
            notes.append(
                "Stopped: not enough quota left for another write. "
                "Use Resume unfinished sorts after midnight US Pacific."
            )
            break
        notes.append(
            sort_playlist(
                pid,
                by=by,
                reverse=reverse,
                dry_run=dry_run,
                title=names.get(pid),
                on_progress=on_progress,
                client=yt,
            )
        )
        if not dry_run:
            mark_sort_done(pid, by)
    return "\n\n".join(notes)


def resume_sorts(
    *,
    on_progress: Optional[Callable[[int, int], None]] = None,
    client: Optional[YouTubeClient] = None,
) -> str:
    """
    PURPOSE:
        Continue pending sort jobs after quota reset.

    INTERNAL LOGIC:
        Loads pending_sorts; runs sort_playlist until quota is too low.

    EXAMPLE INVOCATION:
        resume_sorts()
    """
    from ytpm.jobs import pending_sorts

    jobs = pending_sorts()
    if not jobs:
        return "No unfinished sorts in the queue."
    notes: List[str] = []
    yt = get_client(client)
    for job in jobs:
        if remaining_units() < WRITE_UNITS:
            notes.append(
                "Stopped: not enough quota left. Retry after midnight US Pacific."
            )
            break
        pid = str(job.get("playlist_id") or "")
        by = str(job.get("by") or "title")
        reverse = bool(job.get("reverse"))
        title = str(job.get("title") or pid)
        notes.append(
            sort_playlist(
                pid,
                by=by,  # type: ignore[arg-type]
                reverse=reverse,
                title=title,
                on_progress=on_progress,
                client=yt,
            )
        )
        mark_sort_done(pid, by)
    return "\n\n".join(notes)
