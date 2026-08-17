"""
PURPOSE:
    Tests for the local quota ledger (Pacific-day reset, remaining units).

INTERNAL LOGIC:
    Monkeypatches LEDGER_PATH onto a temp file so the real ledger is untouched.

EXAMPLE INVOCATION:
    pytest tests/test_quota.py
"""

from __future__ import annotations

from pathlib import Path

import ytpm.quota as quota


def test_add_units_and_remaining(tmp_path: Path, monkeypatch: object) -> None:
    """PURPOSE: Writes decrement the 10,000 unit local meter."""
    path = tmp_path / "quota_ledger.json"
    monkeypatch.setattr(quota, "LEDGER_PATH", path)
    quota.save_ledger(quota._empty())
    quota.add_units(50, is_write=True)
    quota.add_units(1, is_write=False)
    assert quota.remaining_units() == quota.DAILY_UNITS - 51
    text = quota.meter_text()
    assert "left" in text
    assert quota.cost_for_http_method("POST") == (50, True)
    assert quota.cost_for_http_method("GET") == (1, False)


def test_write_events_record_method_and_id(tmp_path: Path, monkeypatch: object) -> None:
    """PURPOSE: Each write stores method, resource id, and units for Cloud reconciliation."""
    path = tmp_path / "quota_ledger.json"
    monkeypatch.setattr(quota, "LEDGER_PATH", path)
    quota.save_ledger(quota._empty())
    quota.add_units(
        50,
        is_write=True,
        method="playlistItems.delete",
        resource_id="UExxx",
    )
    writes = quota.recent_writes()
    assert len(writes) == 1
    assert writes[0]["method"] == "playlistItems.delete"
    assert writes[0]["id"] == "UExxx"
    assert writes[0]["units"] == 50
