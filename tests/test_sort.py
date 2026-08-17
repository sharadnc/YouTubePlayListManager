"""
PURPOSE:
    Tests for sort planning, placeholder-safe dedupe, and move counting.

INTERNAL LOGIC:
    Builds PlaylistItem fixtures in memory; no YouTube API calls.

EXAMPLE INVOCATION:
    pytest tests/test_sort.py
"""

from __future__ import annotations

from datetime import datetime, timezone

from ytpm.models import PlaylistItem
from ytpm.ops.sort import dedupe_after_title_normalize, plan_sort
from ytpm.youtube_client import count_position_moves, is_placeholder_title


def _item(
    iid: str,
    vid: str,
    title: str,
    pos: int,
    *,
    channel: str = "",
    seconds: int = 0,
    published: datetime | None = None,
) -> PlaylistItem:
    """
    PURPOSE:
        Build a PlaylistItem fixture.

    INTERNAL LOGIC:
        Fills required fields; optional duration/channel/date.

    EXAMPLE INVOCATION:
        _item("a", "v1", "Song", 0)
    """
    return PlaylistItem(
        id=iid,
        video_id=vid,
        title=title,
        position=pos,
        channel_title=channel,
        duration_seconds=seconds,
        published_at=published,
    )


def test_placeholder_titles_are_not_merged() -> None:
    """PURPOSE: Deleted/Private placeholders must not collapse into one row."""
    items = [
        _item("a", "v1", "Deleted video", 0),
        _item("b", "v2", "Private video", 1),
        _item("c", "v3", "Deleted video", 2),
    ]
    kept, dropped = dedupe_after_title_normalize(items)
    assert is_placeholder_title("Deleted video") is True
    assert {item.video_id for item in kept} == {"v1", "v2", "v3"}
    assert dropped == []


def test_same_collapsed_title_is_duplicate() -> None:
    """PURPOSE: Extra spaces must not create a second keep-key."""
    items = [
        _item("a", "v1", "Foo  Bar", 0),
        _item("b", "v2", "Foo Bar", 1),
    ]
    kept, dropped = dedupe_after_title_normalize(items)
    assert len(kept) == 1
    assert kept[0].video_id == "v1"
    assert kept[0].title == "Foo Bar"
    assert len(dropped) == 1
    assert dropped[0].video_id == "v2"


def test_same_video_id_is_duplicate() -> None:
    """PURPOSE: Later copies of the same video id are dropped."""
    items = [
        _item("a", "v1", "Song", 0),
        _item("b", "v1", "Song", 1),
    ]
    kept, dropped = dedupe_after_title_normalize(items)
    assert [item.id for item in kept] == ["a"]
    assert [item.id for item in dropped] == ["b"]


def test_plan_sort_title_orders_az() -> None:
    """PURPOSE: Title plan is A–Z after collapse."""
    items = [
        _item("a", "v1", "zeta", 0),
        _item("b", "v2", "Alpha", 1),
        _item("c", "v3", "mid", 2),
    ]
    plan = plan_sort(items, "title")
    assert [item.video_id for item in plan.ordered] == ["v2", "v3", "v1"]
    assert plan.move_count == count_position_moves(plan.ordered)


def test_plan_sort_duration_and_channel() -> None:
    """PURPOSE: Duration/channel keys order remaining items."""
    items = [
        _item("a", "v1", "A", 0, channel="Zed", seconds=90),
        _item("b", "v2", "B", 1, channel="Amy", seconds=10),
    ]
    by_dur = plan_sort(items, "duration")
    assert [item.video_id for item in by_dur.ordered] == ["v2", "v1"]
    by_ch = plan_sort(items, "channel")
    assert [item.video_id for item in by_ch.ordered] == ["v2", "v1"]


def test_plan_sort_date_keeps_oldest_duplicate() -> None:
    """PURPOSE: Date sort keep_key prefers the earliest publishedAt copy."""
    early = datetime(2020, 1, 1, tzinfo=timezone.utc)
    late = datetime(2024, 1, 1, tzinfo=timezone.utc)
    items = [
        _item("new", "v1", "Song", 0, published=late),
        _item("old", "v1", "Song", 1, published=early),
    ]
    plan = plan_sort(items, "date")
    assert [item.id for item in plan.ordered] == ["old"]
    assert plan.dropped[0].id == "new"


def test_count_position_moves_already_ordered() -> None:
    """PURPOSE: No writes when live positions already match target order."""
    items = [
        _item("a", "v1", "A", 0),
        _item("b", "v2", "B", 1),
        _item("c", "v3", "C", 2),
    ]
    plan = plan_sort(items, "title")
    assert plan.move_count == 0
    assert plan.write_ops == 0


def test_plan_sort_does_not_mutate_source_titles() -> None:
    """PURPOSE: GUI quota estimate must not rewrite cached PlaylistItem titles."""
    items = [_item("a", "v1", "Foo  Bar", 0)]
    plan = plan_sort(items, "title")
    assert items[0].title == "Foo  Bar"
    assert plan.ordered[0].title == "Foo Bar"
