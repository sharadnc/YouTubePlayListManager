"""
PURPOSE:
    Local YouTube Data API quota ledger (Google does not expose remaining units).

INTERNAL LOGIC:
    Counts 1 unit for GET/list and 50 for write methods. Resets at midnight
    US Pacific. Persists to quota_ledger.json under the project root.

EXAMPLE INVOCATION:
    from ytpm.quota import add_units, remaining_units
    add_units(50)
    left = remaining_units()
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from ytpm.config import PROJECT_ROOT

logger = logging.getLogger(__name__)
AUDIT = logging.getLogger("ytpm.audit")

DAILY_UNITS: int = 10_000
WRITE_UNITS: int = 50
READ_UNITS: int = 1
LEDGER_PATH: Path = PROJECT_ROOT / "quota_ledger.json"
MAX_EVENTS: int = 1000
_PACIFIC = ZoneInfo("America/Los_Angeles")


def pacific_today() -> str:
    """
    PURPOSE:
        Return today's date in US Pacific time (quota reset timezone).

    INTERNAL LOGIC:
        datetime.now in America/Los_Angeles, ISO date.

    EXAMPLE INVOCATION:
        pacific_today()  # "2026-08-16"
    """
    return datetime.now(_PACIFIC).date().isoformat()


def _empty() -> Dict[str, Any]:
    """
    PURPOSE:
        Build a fresh ledger for the current Pacific day.

    INTERNAL LOGIC:
        Zero used units and write/read counters.

    EXAMPLE INVOCATION:
        _empty()
    """
    return {
        "pacific_date": pacific_today(),
        "units_used": 0,
        "writes": 0,
        "reads": 0,
        "events": [],
    }


def load_ledger() -> Dict[str, Any]:
    """
    PURPOSE:
        Read the ledger, resetting if the Pacific date rolled over.

    INTERNAL LOGIC:
        JSON load; missing/invalid/stale date → empty ledger.

    EXAMPLE INVOCATION:
        load_ledger()
    """
    today = pacific_today()
    if not LEDGER_PATH.is_file():
        return _empty()
    try:
        data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Quota ledger unreadable: %s", exc)
        return _empty()
    if str(data.get("pacific_date") or "") != today:
        return _empty()
    data.setdefault("units_used", 0)
    data.setdefault("writes", 0)
    data.setdefault("reads", 0)
    data.setdefault("events", [])
    return data


def save_ledger(data: Dict[str, Any]) -> None:
    """
    PURPOSE:
        Persist the quota ledger to disk.

    INTERNAL LOGIC:
        Writes pretty JSON; logs OS errors.

    EXAMPLE INVOCATION:
        save_ledger(load_ledger())
    """
    try:
        LEDGER_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Quota ledger save failed: %s", exc)


def add_units(
    units: int,
    *,
    is_write: bool = False,
    method: str = "",
    resource_id: str = "",
) -> int:
    """
    PURPOSE:
        Add spent units to today's ledger and return the new total used.

    INTERNAL LOGIC:
        load → increment → append an audit event (capped) → save.
        Writes also emit ytpm.audit so the GUI log can show id/method/units.

    EXAMPLE INVOCATION:
        add_units(50, is_write=True, method="playlistItems.delete", resource_id="UEx")
    """
    data = load_ledger()
    spent = max(0, units)
    data["units_used"] = int(data.get("units_used", 0)) + spent
    if is_write:
        data["writes"] = int(data.get("writes", 0)) + 1
    else:
        data["reads"] = int(data.get("reads", 0)) + 1
    events: List[Dict[str, Any]] = list(data.get("events") or [])
    event: Dict[str, Any] = {
        "ts": datetime.now(_PACIFIC).isoformat(timespec="seconds"),
        "method": method or ("write" if is_write else "read"),
        "id": resource_id or "",
        "units": spent,
        "write": bool(is_write),
    }
    events.append(event)
    data["events"] = events[-MAX_EVENTS:]
    save_ledger(data)
    if is_write:
        AUDIT.info(
            "WRITE %s id=%s units=%s",
            event["method"],
            event["id"] or "-",
            spent,
        )
    return int(data["units_used"])


def recent_writes(*, limit: int = 50) -> List[Dict[str, Any]]:
    """
    PURPOSE:
        Return today's write events for reconciling with Google Cloud quota.

    INTERNAL LOGIC:
        Filters ledger events where write is True; newest last, then tail.

    EXAMPLE INVOCATION:
        recent_writes(limit=20)
    """
    events = [
        ev
        for ev in load_ledger().get("events", [])
        if ev.get("write")
    ]
    return events[-max(0, limit) :]


def remaining_units() -> int:
    """
    PURPOSE:
        Estimate unused units remaining in the default 10,000 daily pool.

    INTERNAL LOGIC:
        max(0, DAILY_UNITS - used).

    EXAMPLE INVOCATION:
        remaining_units()
    """
    used = int(load_ledger().get("units_used", 0))
    return max(0, DAILY_UNITS - used)


def meter_text() -> str:
    """
    PURPOSE:
        One-line quota status for the GUI.

    INTERNAL LOGIC:
        Remaining / daily, Pacific date, write count.

    EXAMPLE INVOCATION:
        meter_text()
    """
    data = load_ledger()
    left = remaining_units()
    return (
        f"Quota ~{left:,} / {DAILY_UNITS:,} left "
        f"(PT {data.get('pacific_date')}, {data.get('writes', 0)} writes)"
    )


def cost_for_http_method(method: str) -> tuple[int, bool]:
    """
    PURPOSE:
        Map an HTTP method to Data API unit cost.

    INTERNAL LOGIC:
        POST/PUT/PATCH/DELETE → 50 write; else 1 read.

    EXAMPLE INVOCATION:
        cost_for_http_method("POST")  # (50, True)
    """
    verb = (method or "GET").upper()
    if verb in {"POST", "PUT", "PATCH", "DELETE"}:
        return WRITE_UNITS, True
    return READ_UNITS, False
