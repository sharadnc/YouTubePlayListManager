"""
PURPOSE:
    Persist unfinished sort jobs so work can resume after quota reset.

INTERNAL LOGIC:
    JSON queue of playlist ids + sort key. Status pending/done. Jobs have
    stable ids so the GUI can drop or reorder them.

EXAMPLE INVOCATION:
    from ytpm.jobs import enqueue_sorts, pending_sorts
    enqueue_sorts(["PLa"], by="title")
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ytpm.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

QUEUE_PATH: Path = PROJECT_ROOT / "sort_queue.json"


def _new_job_id() -> str:
    """
    PURPOSE:
        Allocate a stable id so the GUI can drop/reorder a job.

    INTERNAL LOGIC:
        12-char uuid4 hex.

    EXAMPLE INVOCATION:
        _new_job_id()  # "a1b2c3d4e5f6"
    """
    return uuid.uuid4().hex[:12]


def _ensure_ids(data: Dict[str, Any]) -> bool:
    """
    PURPOSE:
        Backfill job ids on queues written before ids existed.

    INTERNAL LOGIC:
        Mutates jobs in place; returns True if any id was added.

    EXAMPLE INVOCATION:
        changed = _ensure_ids(load_queue())
    """
    changed = False
    for job in data.get("jobs", []):
        if not job.get("id"):
            job["id"] = _new_job_id()
            changed = True
    return changed


def load_queue() -> Dict[str, Any]:
    """
    PURPOSE:
        Load the sort queue from disk.

    INTERNAL LOGIC:
        Missing/invalid file → empty jobs list.

    EXAMPLE INVOCATION:
        load_queue()
    """
    if not QUEUE_PATH.is_file():
        return {"jobs": []}
    try:
        data = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Sort queue unreadable: %s", exc)
        return {"jobs": []}
    data.setdefault("jobs", [])
    if _ensure_ids(data):
        save_queue(data)
    return data


def save_queue(data: Dict[str, Any]) -> None:
    """
    PURPOSE:
        Write the sort queue JSON.

    INTERNAL LOGIC:
        Pretty-print; log OS errors.

    EXAMPLE INVOCATION:
        save_queue({"jobs": []})
    """
    try:
        QUEUE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Sort queue save failed: %s", exc)


def enqueue_sorts(
    playlist_ids: List[str],
    *,
    by: str,
    reverse: bool = False,
    titles: Dict[str, str] | None = None,
) -> None:
    """
    PURPOSE:
        Append pending sort jobs, skipping ids already queued as pending.

    INTERNAL LOGIC:
        Dedupes pending playlist ids. A later enqueue for the same id updates
        by/reverse/title so Sort by Date can replace a queued Sort by Title.

    EXAMPLE INVOCATION:
        enqueue_sorts(["PLxxx"], by="title", titles={"PLxxx": "2024"})
    """
    data = load_queue()
    names = titles or {}
    for pid in playlist_ids:
        replaced = False
        for job in data["jobs"]:
            if job.get("status") != "pending" or job.get("playlist_id") != pid:
                continue
            job["by"] = by
            job["reverse"] = reverse
            if pid in names:
                job["title"] = names[pid]
            if not job.get("id"):
                job["id"] = _new_job_id()
            replaced = True
            break
        if replaced:
            continue
        data["jobs"].append(
            {
                "id": _new_job_id(),
                "playlist_id": pid,
                "title": names.get(pid, pid),
                "by": by,
                "reverse": reverse,
                "status": "pending",
            }
        )
    save_queue(data)


def pending_sorts() -> List[Dict[str, Any]]:
    """
    PURPOSE:
        Return jobs still waiting to run.

    INTERNAL LOGIC:
        Filters status == pending.

    EXAMPLE INVOCATION:
        pending_sorts()
    """
    return [job for job in load_queue().get("jobs", []) if job.get("status") == "pending"]


def mark_sort_done(playlist_id: str, by: str) -> None:
    """
    PURPOSE:
        Mark the first matching pending job as done.

    INTERNAL LOGIC:
        Mutates the first pending job with same id and by.

    EXAMPLE INVOCATION:
        mark_sort_done("PLxxx", "title")
    """
    data = load_queue()
    for job in data["jobs"]:
        if job.get("status") != "pending":
            continue
        if job.get("playlist_id") == playlist_id and job.get("by") == by:
            job["status"] = "done"
            break
    save_queue(data)


def list_jobs() -> List[Dict[str, Any]]:
    """
    PURPOSE:
        Return every queued job (pending and done) in run order.

    INTERNAL LOGIC:
        load_queue jobs list as-is.

    EXAMPLE INVOCATION:
        list_jobs()
    """
    return list(load_queue().get("jobs", []))


def drop_job(job_id: str) -> bool:
    """
    PURPOSE:
        Remove one job (pending or done) from the queue.

    INTERNAL LOGIC:
        Filters out matching id; returns True if a row was removed.

    EXAMPLE INVOCATION:
        drop_job("a1b2c3d4e5f6")
    """
    data = load_queue()
    before = len(data["jobs"])
    data["jobs"] = [job for job in data["jobs"] if str(job.get("id")) != str(job_id)]
    if len(data["jobs"]) == before:
        return False
    save_queue(data)
    return True


def move_job(job_id: str, delta: int) -> bool:
    """
    PURPOSE:
        Reorder a job in the queue (negative delta = earlier / up).

    INTERNAL LOGIC:
        Finds the job, pops it, inserts at index+delta clamped to bounds.

    EXAMPLE INVOCATION:
        move_job("a1b2c3d4e5f6", -1)  # move up
    """
    if delta == 0:
        return False
    data = load_queue()
    jobs: List[Dict[str, Any]] = data["jobs"]
    index: Optional[int] = None
    for i, job in enumerate(jobs):
        if str(job.get("id")) == str(job_id):
            index = i
            break
    if index is None:
        return False
    new_index = max(0, min(len(jobs) - 1, index + delta))
    if new_index == index:
        return False
    job = jobs.pop(index)
    jobs.insert(new_index, job)
    save_queue(data)
    return True


def job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    """
    PURPOSE:
        Look up one queue row by id.

    INTERNAL LOGIC:
        Linear scan of list_jobs.

    EXAMPLE INVOCATION:
        job_by_id("a1b2c3d4e5f6")
    """
    for job in list_jobs():
        if str(job.get("id")) == str(job_id):
            return job
    return None


def clear_done_jobs() -> None:
    """
    PURPOSE:
        Drop completed jobs so the file stays small.

    INTERNAL LOGIC:
        Keeps only pending.

    EXAMPLE INVOCATION:
        clear_done_jobs()
    """
    data = load_queue()
    data["jobs"] = [job for job in data["jobs"] if job.get("status") == "pending"]
    save_queue(data)
