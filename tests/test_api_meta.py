"""
PURPOSE:
    Tests for API request metadata used by the quota write audit log.

INTERNAL LOGIC:
    Dummy request objects (uri/method/body); no network.

EXAMPLE INVOCATION:
    pytest tests/test_api_meta.py
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

from ytpm.youtube_client import _api_call_meta


def _req(method: str, uri: str, body: Optional[Any] = None) -> SimpleNamespace:
    """
    PURPOSE:
        Build a stand-in for googleapiclient HttpRequest.

    INTERNAL LOGIC:
        SimpleNamespace with method, uri, body.

    EXAMPLE INVOCATION:
        _req("DELETE", "https://example/youtube/v3/playlistItems?id=UE1")
    """
    return SimpleNamespace(method=method, uri=uri, body=body)


def test_api_meta_delete_query_id() -> None:
    """PURPOSE: DELETE playlistItems?id= maps to playlistItems.delete."""
    method, rid = _api_call_meta(
        _req("DELETE", "https://youtube.googleapis.com/youtube/v3/playlistItems?id=UExxx"),
        {},
    )
    assert method == "playlistItems.delete"
    assert rid == "UExxx"


def test_api_meta_update_body_id() -> None:
    """PURPOSE: PUT/PATCH with JSON body id uses that id."""
    method, rid = _api_call_meta(
        _req(
            "PUT",
            "https://youtube.googleapis.com/youtube/v3/playlists?part=snippet",
            body='{"id": "PLyyy", "snippet": {"title": "T"}}',
        ),
        {},
    )
    assert method == "playlists.update"
    assert rid == "PLyyy"


def test_api_meta_insert_response_id() -> None:
    """PURPOSE: Insert id comes from the API response when the body has none."""
    method, rid = _api_call_meta(
        _req("POST", "https://youtube.googleapis.com/youtube/v3/playlists"),
        {"id": "PLnew"},
    )
    assert method == "playlists.insert"
    assert rid == "PLnew"
