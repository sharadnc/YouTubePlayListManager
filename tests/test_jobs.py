"""
PURPOSE:
    Tests for the sort job queue (pending replace on the same playlist id).

INTERNAL LOGIC:
    Monkeypatches QUEUE_PATH onto a temp file.

EXAMPLE INVOCATION:
    pytest tests/test_jobs.py
"""

from __future__ import annotations

from pathlib import Path

import ytpm.jobs as jobs


def test_enqueue_replaces_pending_sort_key(tmp_path: Path, monkeypatch: object) -> None:
    """PURPOSE: A later Sort by Date must replace a queued Sort by Title."""
    path = tmp_path / "sort_queue.json"
    monkeypatch.setattr(jobs, "QUEUE_PATH", path)
    jobs.enqueue_sorts(["PLxxx"], by="title", titles={"PLxxx": "2024"})
    jobs.enqueue_sorts(["PLxxx"], by="date", titles={"PLxxx": "2024"})
    pending = jobs.pending_sorts()
    assert len(pending) == 1
    assert pending[0]["by"] == "date"
    jobs.mark_sort_done("PLxxx", "date")
    assert jobs.pending_sorts() == []


def test_drop_and_reorder_jobs(tmp_path: Path, monkeypatch: object) -> None:
    """PURPOSE: GUI can drop a job or move it earlier in the queue."""
    path = tmp_path / "sort_queue.json"
    monkeypatch.setattr(jobs, "QUEUE_PATH", path)
    jobs.enqueue_sorts(["PLa"], by="title", titles={"PLa": "A"})
    jobs.enqueue_sorts(["PLb"], by="date", titles={"PLb": "B"})
    queued = jobs.list_jobs()
    assert [j["playlist_id"] for j in queued] == ["PLa", "PLb"]
    first_id = str(queued[0]["id"])
    second_id = str(queued[1]["id"])
    assert jobs.move_job(second_id, -1) is True
    assert [j["playlist_id"] for j in jobs.list_jobs()] == ["PLb", "PLa"]
    assert jobs.drop_job(first_id) is True
    left = jobs.list_jobs()
    assert len(left) == 1
    assert left[0]["playlist_id"] == "PLb"
