"""
PURPOSE:
    Google OAuth2 for YouTube Data API (installed-app flow) and credential persistence.

INTERNAL LOGIC:
    1. Load token.json if present and refresh when expired.
    2. Otherwise run InstalledAppFlow with client id/secret from Settings.
    3. Build googleapiclient discovery service for YouTube v3.

EXAMPLE INVOCATION:
    from ytpm.auth import get_youtube_service, run_oauth_flow
    run_oauth_flow()
    yt = get_youtube_service()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ytpm.config import Settings, get_settings

logger = logging.getLogger(__name__)

SCOPES: list[str] = ["https://www.googleapis.com/auth/youtube.force-ssl"]


class AuthError(RuntimeError):
    """
    PURPOSE:
        Raised when OAuth credentials are missing or invalid.

    INTERNAL LOGIC:
        Thin RuntimeError subclass for callers to catch specifically.

    EXAMPLE INVOCATION:
        raise AuthError("Run auth first")
    """


def _client_config(settings: Settings) -> dict[str, Any]:
    """
    PURPOSE:
        Build InstalledAppFlow client_config dict from Settings.

    INTERNAL LOGIC:
        Maps YOUTUBE_CLIENT_ID/SECRET into the installed-app JSON shape Google expects.

    EXAMPLE INVOCATION:
        _client_config(get_settings())
    """
    if not settings.has_oauth_client():
        raise AuthError(
            "YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env "
            "(copy from .env.example and fill from Google Cloud Console)."
        )
    return {
        "installed": {
            "client_id": settings.youtube_client_id.strip(),
            "client_secret": settings.youtube_client_secret.strip(),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def load_credentials(settings: Optional[Settings] = None) -> Optional[Credentials]:
    """
    PURPOSE:
        Load and optionally refresh stored OAuth credentials.

    INTERNAL LOGIC:
        Reads token path; refreshes if expired and refresh_token present; saves updates.

    EXAMPLE INVOCATION:
        creds = load_credentials()
    """
    settings = settings or get_settings()
    token_path = settings.token_path()
    if not token_path.is_file():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    except Exception as exc:
        logger.exception("Failed to load token from %s: %s", token_path, exc)
        return None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_credentials(creds, settings)
        except Exception as exc:
            logger.warning("Token refresh failed: %s", exc)
            return None
    if creds and creds.valid:
        return creds
    return None


def save_credentials(creds: Credentials, settings: Optional[Settings] = None) -> None:
    """
    PURPOSE:
        Persist OAuth credentials to token.json.

    INTERNAL LOGIC:
        Writes authorized-user JSON; creates parent directories as needed.

    EXAMPLE INVOCATION:
        save_credentials(creds)
    """
    settings = settings or get_settings()
    token_path = settings.token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    logger.info("Saved OAuth token to %s", token_path)


def clear_credentials(settings: Optional[Settings] = None) -> None:
    """
    PURPOSE:
        Delete cached token so the next connect starts a fresh consent flow.

    INTERNAL LOGIC:
        Unlinks token file if it exists.

    EXAMPLE INVOCATION:
        clear_credentials()
    """
    settings = settings or get_settings()
    token_path = settings.token_path()
    if token_path.is_file():
        token_path.unlink()
        logger.info("Removed OAuth token at %s", token_path)


def is_authenticated(settings: Optional[Settings] = None) -> bool:
    """
    PURPOSE:
        Whether a valid (possibly refreshed) credential is available.

    INTERNAL LOGIC:
        load_credentials() is not None.

    EXAMPLE INVOCATION:
        if is_authenticated(): ...
    """
    return load_credentials(settings) is not None


def run_oauth_flow(settings: Optional[Settings] = None, *, force: bool = False) -> Credentials:
    """
    PURPOSE:
        Run browser OAuth consent and save the resulting credentials.

    INTERNAL LOGIC:
        If force, clear existing token. Else reuse valid token. Otherwise InstalledAppFlow.

    EXAMPLE INVOCATION:
        run_oauth_flow()
        run_oauth_flow(force=True)  # reconnect / switch account
    """
    settings = settings or get_settings()
    if force:
        clear_credentials(settings)
    else:
        existing = load_credentials(settings)
        if existing:
            return existing
    flow = InstalledAppFlow.from_client_config(_client_config(settings), SCOPES)
    # Opens system browser; user grants YouTube playlist access.
    creds = flow.run_local_server(port=0, prompt="consent")
    save_credentials(creds, settings)
    return creds


def get_youtube_service(settings: Optional[Settings] = None) -> Any:
    """
    PURPOSE:
        Build an authenticated YouTube Data API v3 discovery client.

    INTERNAL LOGIC:
        Requires valid credentials; builds 'youtube' v3 resource.

    EXAMPLE INVOCATION:
        yt = get_youtube_service()
        yt.playlists().list(part="snippet", mine=True).execute()
    """
    settings = settings or get_settings()
    creds = load_credentials(settings)
    if not creds:
        raise AuthError(
            "Not authenticated. Run `python -m ytpm auth` or use Connect Google Account in the GUI."
        )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)
