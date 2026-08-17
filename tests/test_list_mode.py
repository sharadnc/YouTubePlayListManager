"""
PURPOSE:
    Tests for list-mode parse/roundtrip and apply-plan diffs (no API).

INTERNAL LOGIC:
    Temp files + PlaylistItem fixtures; build_apply_plan is pure.

EXAMPLE INVOCATION:
    pytest tests/test_list_mode.py
"""

from __future__ import annotations

import os
from pathlib import Path

from ytpm.list_mode import (
    build_apply_plan,
    line_to_text,
    list_snapshots,
    parse_line,
    read_list_file,
    snapshot_playlist,
    write_sorted_list_file,
)
from ytpm.models import ListModeLine, PlaylistItem


def test_parse_line_ignores_comments_and_blanks() -> None:
    """PURPOSE: Headers and empty lines are not data rows."""
    assert parse_line("") is None
    assert parse_line("# ID: PLxxx") is None
    row = parse_line("abc\tTitle\tChan\tUEx")
    assert row is not None
    assert row.video_id == "abc"
    assert row.title == "Title"
    assert row.channel == "Chan"
    assert row.playlist_item_id == "UEx"


def test_parse_line_video_id_only() -> None:
    """PURPOSE: A lone video id is a valid list-mode row."""
    row = parse_line("dQw4w9WgXcQ")
    assert row is not None
    assert row.video_id == "dQw4w9WgXcQ"
    assert row.playlist_item_id == ""


def test_write_and_read_list_file_roundtrip(tmp_path: Path) -> None:
    """PURPOSE: Intended order files round-trip through parse_line."""
    items = [
        PlaylistItem(id="UEa", video_id="v1", title="One", channel_title="C", position=0),
        PlaylistItem(id="UEb", video_id="v2", title="Two", channel_title="D", position=1),
    ]
    path = write_sorted_list_file("PLxxx", "Mix", items, out_dir=tmp_path)
    pid, rows = read_list_file(path)
    assert pid == "PLxxx"
    assert [row.video_id for row in rows] == ["v1", "v2"]
    assert [row.playlist_item_id for row in rows] == ["UEa", "UEb"]
    assert parse_line(line_to_text(rows[0])) == rows[0]


def test_build_apply_plan_reorder_only() -> None:
    """PURPOSE: Same membership, swapped order → reorders, no delete/insert."""
    live = [
        PlaylistItem(id="UEa", video_id="v1", title="One", position=0),
        PlaylistItem(id="UEb", video_id="v2", title="Two", position=1),
    ]
    desired = [
        ListModeLine(video_id="v2", title="Two", playlist_item_id="UEb"),
        ListModeLine(video_id="v1", title="One", playlist_item_id="UEa"),
    ]
    plan = build_apply_plan("PLxxx", Path("mix.txt"), desired, live)
    assert plan.delete_item_ids == []
    assert plan.insert_video_ids == []
    assert [row[0] for row in plan.reorder] == ["UEb", "UEa"]


def test_build_apply_plan_delete_and_insert() -> None:
    """PURPOSE: Dropped live rows delete; unknown ids insert."""
    live = [
        PlaylistItem(id="UEa", video_id="v1", title="Keep", position=0),
        PlaylistItem(id="UEb", video_id="gone", title="Drop", position=1),
    ]
    desired = [
        ListModeLine(video_id="v1", title="Keep", playlist_item_id="UEa"),
        ListModeLine(video_id="newvid", title="New", playlist_item_id=""),
    ]
    plan = build_apply_plan("PLxxx", Path("mix.txt"), desired, live)
    assert plan.delete_item_ids == ["UEb"]
    assert plan.insert_video_ids == [("newvid", 1)]
    assert plan.reorder[0][0] == "UEa"


def test_list_snapshots_newest_first(tmp_path: Path, monkeypatch: object) -> None:
    """PURPOSE: Undo picker sees the last N snapshots, newest first."""
    from ytpm import list_mode

    class _Settings:
        """PURPOSE: Point list_dir at a temp folder for this test."""

        def list_dir(self) -> Path:
            """PURPOSE: Return the temp project list_mode root."""
            return tmp_path

    monkeypatch.setattr(list_mode, "get_settings", lambda: _Settings())
    items = [PlaylistItem(id="UEa", video_id="v1", title="One", position=0)]
    older = snapshot_playlist("PLxxx", "Mix", items)
    newer = snapshot_playlist("PLxxx", "Mix", items)
    other = snapshot_playlist("PLother", "Other", items)
    stamp = newer.stat().st_mtime
    os.utime(older, (stamp - 30, stamp - 30))
    os.utime(newer, (stamp, stamp))
    ranked = list_snapshots("PLxxx", limit=20)
    assert older in ranked
    assert newer in ranked
    assert other not in ranked
    assert ranked[0] == newer
    assert list_snapshots("PLxxx", limit=1) == [newer]
