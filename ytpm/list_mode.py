"""
PURPOSE:
    List mode: export each playlist to a text file and apply file edits remotely.

INTERNAL LOGIC:
    Export writes tab-separated lines in playlist order. Apply diffs order/deletes/
    inserts (including duplicated lines and cross-playlist copies).

EXAMPLE INVOCATION:
    from ytpm.list_mode import export_all, apply_all
    export_all()
    apply_all(dry_run=True)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ytpm.config import get_settings
from ytpm.errors import PlaylistOrderError, QuotaExceededError
from ytpm.models import ListModeLine, Playlist, PlaylistItem
from ytpm.ops.playlists import get_client, list_playlists
from ytpm.quota import WRITE_UNITS
from ytpm.youtube_client import YouTubeClient

logger = logging.getLogger(__name__)

_SAFE = re.compile(r"[^\w\-]+", re.UNICODE)


def _safe_stem(name: str, playlist_id: str) -> str:
    """
    PURPOSE:
        Build a filesystem-safe stem for a playlist list-mode file.

    INTERNAL LOGIC:
        Sanitizes title and appends short id suffix for uniqueness.

    EXAMPLE INVOCATION:
        _safe_stem("My Mix", "PLabcdef")
    """
    cleaned = _SAFE.sub("_", name.strip()) or "playlist"
    return f"{cleaned[:60]}__{playlist_id[-8:]}"


def line_to_text(line: ListModeLine) -> str:
    """
    PURPOSE:
        Serialize a list-mode row to a tab-separated line.

    INTERNAL LOGIC:
        videoId, title, channel, playlistItemId.

    EXAMPLE INVOCATION:
        line_to_text(ListModeLine(video_id="a", title="t", channel="c", playlist_item_id="u"))
    """
    return f"{line.video_id}\t{line.title}\t{line.channel}\t{line.playlist_item_id}"


def parse_line(raw: str) -> Optional[ListModeLine]:
    """
    PURPOSE:
        Parse one list-mode file line into a ListModeLine.

    INTERNAL LOGIC:
        Ignores blanks and # comments; splits on tabs (min video_id).

    EXAMPLE INVOCATION:
        parse_line("abc\\tTitle\\tChan\\tUEx")
    """
    text = raw.strip()
    if not text or text.startswith("#"):
        return None
    parts = text.split("\t")
    video_id = parts[0].strip()
    if not video_id:
        return None
    return ListModeLine(
        video_id=video_id,
        title=parts[1].strip() if len(parts) > 1 else "",
        channel=parts[2].strip() if len(parts) > 2 else "",
        playlist_item_id=parts[3].strip() if len(parts) > 3 else "",
    )


def export_playlist_file(
    playlist: Playlist,
    *,
    out_dir: Optional[Path] = None,
    client: Optional[YouTubeClient] = None,
) -> Path:
    """
    PURPOSE:
        Write one list-mode text file for a playlist.

    INTERNAL LOGIC:
        Header comments + one line per item in position order.

    EXAMPLE INVOCATION:
        export_playlist_file(playlist)
    """
    yt = get_client(client)
    items = yt.list_playlist_items(playlist.id)
    root = out_dir or get_settings().list_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{_safe_stem(playlist.title, playlist.id)}.txt"
    lines = [
        f"# Playlist: {playlist.title}",
        f"# ID: {playlist.id}",
        "# Format: videoId\\ttitle\\tchannel\\tplaylistItemId",
        "# Edit order, delete lines, duplicate lines, or paste lines from other files.",
        "",
    ]
    for item in items:
        lines.append(
            line_to_text(
                ListModeLine(
                    video_id=item.video_id,
                    title=item.title,
                    channel=item.channel_title,
                    playlist_item_id=item.id,
                )
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("List-mode exported %s (%s items) -> %s", playlist.title, len(items), path)
    return path


def write_sorted_list_file(
    playlist_id: str,
    title: str,
    items: List[PlaylistItem],
    *,
    out_dir: Optional[Path] = None,
) -> Path:
    """
    PURPOSE:
        Persist an intended playlist order to list-mode without extra API writes.

    INTERNAL LOGIC:
        Writes the given items in list order so Apply can run after quota resets.

    EXAMPLE INVOCATION:
        write_sorted_list_file("PLxxx", "2026", ordered_items)
    """
    root = out_dir or get_settings().list_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{_safe_stem(title or playlist_id, playlist_id)}.txt"
    lines = [
        f"# Playlist: {title}",
        f"# ID: {playlist_id}",
        "# Format: videoId\\ttitle\\tchannel\\tplaylistItemId",
        "# Intended sort order saved locally (no YouTube writes).",
        "",
    ]
    for item in items:
        lines.append(
            line_to_text(
                ListModeLine(
                    video_id=item.video_id,
                    title=item.title,
                    channel=item.channel_title,
                    playlist_item_id=item.id,
                )
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Saved intended order for %s (%s items) -> %s", title, len(items), path)
    return path


def export_all(
    *,
    out_dir: Optional[Path] = None,
    client: Optional[YouTubeClient] = None,
) -> List[Path]:
    """
    PURPOSE:
        Export all user playlists to list-mode files.

    INTERNAL LOGIC:
        Lists playlists; writes one file each under list dir.

    EXAMPLE INVOCATION:
        export_all()
    """
    yt = get_client(client)
    paths: List[Path] = []
    for pl in list_playlists(yt):
        paths.append(export_playlist_file(pl, out_dir=out_dir, client=yt))
    return paths


def export_playlists(
    playlists: List[Playlist],
    *,
    out_dir: Optional[Path] = None,
    client: Optional[YouTubeClient] = None,
) -> List[Path]:
    """
    PURPOSE:
        Export only the given playlists to list-mode files.

    INTERNAL LOGIC:
        Calls export_playlist_file for each playlist.

    EXAMPLE INVOCATION:
        export_playlists(selected)
    """
    yt = get_client(client)
    return [export_playlist_file(pl, out_dir=out_dir, client=yt) for pl in playlists]


def snapshot_playlist(
    playlist_id: str,
    title: str,
    items: List[PlaylistItem],
) -> Path:
    """
    PURPOSE:
        Save a pre-mutation snapshot for Undo.

    INTERNAL LOGIC:
        Writes a timestamped list-mode file under list_mode/snapshots.

    EXAMPLE INVOCATION:
        snapshot_playlist("PLxxx", "2024", items)
    """
    from datetime import datetime

    root = get_settings().list_dir() / "snapshots"
    root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = root / f"{_safe_stem(title or playlist_id, playlist_id)}_{ts}.txt"
    lines = [
        f"# Playlist: {title}",
        f"# ID: {playlist_id}",
        "# Snapshot for Undo (live order before mutation).",
        "",
    ]
    for item in items:
        lines.append(
            line_to_text(
                ListModeLine(
                    video_id=item.video_id,
                    title=item.title,
                    channel=item.channel_title,
                    playlist_item_id=item.id,
                )
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Snapshot %s -> %s", playlist_id, path)
    return path


def latest_snapshot(playlist_id: str) -> Optional[Path]:
    """
    PURPOSE:
        Find the newest snapshot file for a playlist id.

    INTERNAL LOGIC:
        Scans list_mode/snapshots for matching # ID: header.

    EXAMPLE INVOCATION:
        latest_snapshot("PLxxx")
    """
    root = get_settings().list_dir() / "snapshots"
    if not root.is_dir():
        return None
    matches: List[Path] = []
    for path in root.glob("*.txt"):
        pid, _lines = read_list_file(path)
        if pid == playlist_id:
            matches.append(path)
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def list_snapshots(playlist_id: str, *, limit: int = 20) -> List[Path]:
    """
    PURPOSE:
        List recent Undo snapshots for a playlist, newest first.

    INTERNAL LOGIC:
        Same # ID: match as latest_snapshot; sort by mtime descending; cap limit.

    EXAMPLE INVOCATION:
        list_snapshots("PLxxx", limit=10)
    """
    root = get_settings().list_dir() / "snapshots"
    if not root.is_dir():
        return []
    matches: List[Path] = []
    for path in root.glob("*.txt"):
        pid, _lines = read_list_file(path)
        if pid == playlist_id:
            matches.append(path)
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    cap = max(0, limit)
    return matches[:cap] if cap else matches


def undo_playlist(
    playlist_id: str,
    *,
    snapshot: Optional[Path] = None,
    client: Optional[YouTubeClient] = None,
) -> str:
    """
    PURPOSE:
        Restore a playlist from a chosen snapshot (or the newest).

    INTERNAL LOGIC:
        snapshot path if given, else latest_snapshot; then execute_plan.

    EXAMPLE INVOCATION:
        undo_playlist("PLxxx")
        undo_playlist("PLxxx", snapshot=Path("list_mode/snapshots/x.txt"))
    """
    path = snapshot or latest_snapshot(playlist_id)
    if path is None:
        raise FileNotFoundError(
            "No snapshot found for this playlist. Undo is available after Sort or Clear."
        )
    plan = plan_apply(path, client=client)
    execute_plan(plan, dry_run=False, client=client)
    return f"Restored playlist from snapshot:\n{path}"


def read_list_file(path: Path) -> Tuple[Optional[str], List[ListModeLine]]:
    """
    PURPOSE:
        Read playlist id (from header) and ordered lines from a list-mode file.

    INTERNAL LOGIC:
        Parses ``# ID:`` header and data lines via parse_line.

    EXAMPLE INVOCATION:
        pid, lines = read_list_file(Path("list_mode/x.txt"))
    """
    playlist_id: Optional[str] = None
    lines: List[ListModeLine] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith("# ID:"):
            playlist_id = raw.split(":", 1)[1].strip()
            continue
        parsed = parse_line(raw)
        if parsed:
            lines.append(parsed)
    return playlist_id, lines


@dataclass
class ApplyPlan:
    """
    PURPOSE:
        Describe remote mutations needed to match a list-mode file.

    INTERNAL LOGIC:
        Holds deletes, inserts (video_id + position), and position updates.

    EXAMPLE INVOCATION:
        plan = plan_apply(path)
    """

    playlist_id: str
    path: Path
    delete_item_ids: List[str] = field(default_factory=list)
    insert_video_ids: List[Tuple[str, int]] = field(default_factory=list)
    reorder: List[Tuple[str, str, int]] = field(default_factory=list)  # item_id, video_id, pos
    live_items: List[PlaylistItem] = field(default_factory=list)

    @property
    def op_count(self) -> int:
        """Total planned API operations."""
        return len(self.delete_item_ids) + len(self.insert_video_ids) + len(self.reorder)

    def summary(self) -> str:
        """
        PURPOSE:
            Human-readable dry-run line for this file.

        INTERNAL LOGIC:
            Counts delete/insert/reorder and estimates write units.

        EXAMPLE INVOCATION:
            plan.summary()
        """
        return (
            f"{self.path.name}: delete {len(self.delete_item_ids)}, "
            f"insert {len(self.insert_video_ids)}, "
            f"reorder {len(self.reorder)} "
            f"(~{self.op_count * WRITE_UNITS:,} units)"
        )


def build_apply_plan(
    playlist_id: str,
    path: Path,
    desired: List[ListModeLine],
    live: List[PlaylistItem],
) -> ApplyPlan:
    """
    PURPOSE:
        Diff desired list-mode rows against live items (no API).

    INTERNAL LOGIC:
        Reuses matching playlistItem ids; extra live rows become deletes;
        unmatched desired rows become inserts; kept rows are reorders.

    EXAMPLE INVOCATION:
        plan = build_apply_plan("PLxxx", path, desired, live)
    """
    live_by_id: Dict[str, PlaylistItem] = {item.id: item for item in live}
    used_ids: set[str] = set()
    plan = ApplyPlan(playlist_id=playlist_id, path=path, live_items=list(live))
    assigned: List[Tuple[Optional[str], str]] = []
    for row in desired:
        item_id = row.playlist_item_id
        if item_id and item_id in live_by_id and item_id not in used_ids:
            live_item = live_by_id[item_id]
            if live_item.video_id == row.video_id:
                used_ids.add(item_id)
                assigned.append((item_id, row.video_id))
                continue
        assigned.append((None, row.video_id))
    for item in live:
        if item.id not in used_ids:
            plan.delete_item_ids.append(item.id)
    for index, (item_id, video_id) in enumerate(assigned):
        if item_id is None:
            plan.insert_video_ids.append((video_id, index))
        else:
            plan.reorder.append((item_id, video_id, index))
    return plan


def plan_apply(
    path: Path,
    *,
    client: Optional[YouTubeClient] = None,
) -> ApplyPlan:
    """
    PURPOSE:
        Diff a list-mode file against the live playlist and build an ApplyPlan.

    INTERNAL LOGIC:
        Reads the file, lists live items, then build_apply_plan.

    EXAMPLE INVOCATION:
        plan = plan_apply(Path("list_mode/foo.txt"))
    """
    yt = get_client(client)
    playlist_id, desired = read_list_file(path)
    if not playlist_id:
        raise ValueError(f"Missing '# ID:' header in {path}")
    live = yt.list_playlist_items(playlist_id)
    return build_apply_plan(playlist_id, path, desired, live)


def execute_plan(plan: ApplyPlan, *, dry_run: bool = False, client: Optional[YouTubeClient] = None) -> int:
    """
    PURPOSE:
        Execute (or print) an ApplyPlan against YouTube.

        INTERNAL LOGIC:
            Deletes extras, inserts missing (no position), then apply_item_order.

    EXAMPLE INVOCATION:
        execute_plan(plan, dry_run=True)
    """
    if dry_run:
        logger.info("DRY-RUN %s", plan.summary())
        return plan.op_count
    yt = get_client(client)
    live = plan.live_items or yt.list_playlist_items(plan.playlist_id)
    snapshot_playlist(plan.playlist_id, _list_file_title(plan.path), live)
    for item_id in plan.delete_item_ids:
        yt.delete_playlist_item(item_id)
    for video_id, _pos in plan.insert_video_ids:
        yt.insert_video(plan.playlist_id, video_id)

    _pid, desired = read_list_file(plan.path)
    live = yt.list_playlist_items(plan.playlist_id)
    from collections import defaultdict, deque
    from typing import Deque, DefaultDict

    from ytpm.models import PlaylistItem

    buckets: DefaultDict[str, Deque[PlaylistItem]] = defaultdict(deque)
    for item in live:
        buckets[item.video_id].append(item)

    ordered: List[PlaylistItem] = []
    for index, row in enumerate(desired):
        if not buckets[row.video_id]:
            logger.warning("No live item for video %s at position %s", row.video_id, index)
            continue
        ordered.append(buckets[row.video_id].popleft())
    leftovers = [item for queue in buckets.values() for item in queue]
    for item in leftovers:
        yt.delete_playlist_item(item.id)
    try:
        yt.apply_item_order(plan.playlist_id, ordered)
    except PlaylistOrderError:
        copy = yt.copy_playlist_in_order(
            _list_file_title(plan.path),
            [item.video_id for item in ordered if item.video_id],
            suffix=" (list-mode order)",
        )
        raise PlaylistOrderError(
            f"Membership updates from {plan.path.name} were applied, but YouTube "
            "blocked in-place reordering (Sort is not Manual).\n\n"
            f'Created an ordered copy: "{copy.title}"\n'
            "Set Sort → Manual on the original in Studio to reorder it in place."
        )
    logger.info("Applied list-mode file %s to %s", plan.path.name, plan.playlist_id)
    return plan.op_count


def _list_file_title(path: Path) -> str:
    """
    PURPOSE:
        Read the playlist title comment from a list-mode file.

    INTERNAL LOGIC:
        First ``# Playlist:`` line; falls back to the file stem.

    EXAMPLE INVOCATION:
        _list_file_title(Path("list_mode/Mix__abc.txt"))
    """
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.startswith("# Playlist:"):
                name = raw.split(":", 1)[1].strip()
                if name:
                    return name
    except OSError as exc:
        logger.warning("Could not read list-mode title from %s: %s", path, exc)
    return path.stem


def apply_all(
    *,
    list_dir: Optional[Path] = None,
    dry_run: bool = False,
    client: Optional[YouTubeClient] = None,
) -> str:
    """
    PURPOSE:
        Apply every ``.txt`` list-mode file in the list directory.

    INTERNAL LOGIC:
        Plans and executes each file independently. Quota errors stop the batch;
        other file failures are recorded and later files still run.

    EXAMPLE INVOCATION:
        apply_all(dry_run=True)
    """
    yt = get_client(client)
    root = list_dir or get_settings().list_dir()
    if not root.is_dir():
        raise FileNotFoundError(f"List directory not found: {root}")
    total = 0
    notes: List[str] = []
    for path in sorted(root.glob("*.txt")):
        try:
            plan = plan_apply(path, client=yt)
            total += execute_plan(plan, dry_run=dry_run, client=yt)
            notes.append(plan.summary() if dry_run else f"OK {path.name}")
        except QuotaExceededError as exc:
            notes.append(f"QUOTA {path.name}")
            raise QuotaExceededError(
                f"{exc}\n\nProgress:\n" + "\n".join(notes)
            ) from exc
        except PlaylistOrderError as exc:
            notes.append(f"PARTIAL {path.name}: {exc}")
        except Exception as exc:
            logger.exception("List-mode apply failed for %s", path.name)
            notes.append(f"FAIL {path.name}: {exc}")
    summary = (
        f"{'Dry run' if dry_run else 'Applied'} ~{total} operations.\n" + "\n".join(notes)
    )
    if any(line.startswith("FAIL") for line in notes):
        raise RuntimeError(summary)
    return summary


def estimate_apply_writes(*, list_dir: Optional[Path] = None) -> int:
    """
    PURPOSE:
        Worst-case write count for List Mode Apply (every file line).

    INTERNAL LOGIC:
        Sums parsed data lines across list_mode/*.txt (no API).

    EXAMPLE INVOCATION:
        estimate_apply_writes()
    """
    root = list_dir or get_settings().list_dir()
    if not root.is_dir():
        return 0
    total = 0
    for path in root.glob("*.txt"):
        _pid, lines = read_list_file(path)
        total += len(lines)
    return total
