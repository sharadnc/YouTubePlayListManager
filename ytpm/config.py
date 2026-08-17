"""
PURPOSE:
    Load YTPM settings from environment / .env via Pydantic Settings.

INTERNAL LOGIC:
    Reads YOUTUBE_* and YTPM_* variables; resolves paths relative to project root.

EXAMPLE INVOCATION:
    from ytpm.config import get_settings
    s = get_settings()
    print(s.youtube_client_id)
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _detect_project_root() -> Path:
    """
    PURPOSE:
        Resolve the writable app directory (project folder or .exe folder).

    INTERNAL LOGIC:
        Frozen PyInstaller builds use the executable's parent so .env/token
        live next to the .exe. Source runs use the repo root.

    EXAMPLE INVOCATION:
        _detect_project_root()
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT: Path = _detect_project_root()


class Settings(BaseSettings):
    """
    PURPOSE:
        Validated runtime configuration for OAuth and output directories.

    INTERNAL LOGIC:
        Loads from .env in PROJECT_ROOT; provides Path helpers for token/list/export.

    EXAMPLE INVOCATION:
        Settings()  # reads .env automatically
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    youtube_client_id: str = Field(default="", alias="YOUTUBE_CLIENT_ID")
    youtube_client_secret: str = Field(default="", alias="YOUTUBE_CLIENT_SECRET")
    youtube_token_path: str = Field(default="./token.json", alias="YOUTUBE_TOKEN_PATH")
    ytpm_list_dir: str = Field(default="./list_mode", alias="YTPM_LIST_DIR")
    ytpm_export_dir: str = Field(default="./exports", alias="YTPM_EXPORT_DIR")

    def token_path(self) -> Path:
        """
        PURPOSE:
            Resolve OAuth token file path against project root when relative.

        INTERNAL LOGIC:
            Absolute paths pass through; relative paths join PROJECT_ROOT.

        EXAMPLE INVOCATION:
            get_settings().token_path()
        """
        p = Path(self.youtube_token_path)
        return p if p.is_absolute() else PROJECT_ROOT / p

    def list_dir(self) -> Path:
        """
        PURPOSE:
            Resolve list-mode directory path.

        INTERNAL LOGIC:
            Same relative/absolute rules as token_path.

        EXAMPLE INVOCATION:
            get_settings().list_dir()
        """
        p = Path(self.ytpm_list_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p

    def export_dir(self) -> Path:
        """
        PURPOSE:
            Resolve JSON export directory path.

        INTERNAL LOGIC:
            Same relative/absolute rules as token_path.

        EXAMPLE INVOCATION:
            get_settings().export_dir()
        """
        p = Path(self.ytpm_export_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p

    def has_oauth_client(self) -> bool:
        """
        PURPOSE:
            Whether Client ID and Secret are configured.

        INTERNAL LOGIC:
            Non-empty strip of both credential fields.

        EXAMPLE INVOCATION:
            get_settings().has_oauth_client()
        """
        return bool(self.youtube_client_id.strip() and self.youtube_client_secret.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    PURPOSE:
        Cached singleton Settings instance.

    INTERNAL LOGIC:
        Constructs Settings once per process.

    EXAMPLE INVOCATION:
        get_settings()
    """
    return Settings()


def clear_settings_cache() -> None:
    """
    PURPOSE:
        Drop cached Settings so .env edits are re-read (e.g. after GUI edits).

    INTERNAL LOGIC:
        Calls lru_cache.cache_clear on get_settings.

    EXAMPLE INVOCATION:
        clear_settings_cache()
    """
    get_settings.cache_clear()
