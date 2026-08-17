"""
PURPOSE:
    Tests for the Windows zip packager (secret stripping, zip layout).

INTERNAL LOGIC:
    Uses a fake dist tree under tmp_path; monkeypatches DIST_DIR / RELEASE_DIR.

EXAMPLE INVOCATION:
    pytest tests/test_package_release.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import scripts.package_release as pkg


def test_app_version_matches_package() -> None:
    """PURPOSE: Zip name uses ytpm.__version__ without importing ytpm."""
    import ytpm

    assert pkg._app_version() == ytpm.__version__


def test_should_skip_secrets_and_runtime(tmp_path: Path) -> None:
    """PURPOSE: token.json, logs, and list_mode must not ship."""
    dist = tmp_path / "YTPM"
    dist.mkdir()
    token = dist / "token.json"
    token.write_text("{}", encoding="utf-8")
    log = dist / "gui_crash.log"
    log.write_text("x", encoding="utf-8")
    nested = dist / "list_mode" / "foo.txt"
    nested.parent.mkdir()
    nested.write_text("x", encoding="utf-8")
    exe = dist / "YTPM.exe"
    exe.write_bytes(b"MZ")
    assert pkg._should_skip(token, dist) is True
    assert pkg._should_skip(log, dist) is True
    assert pkg._should_skip(nested, dist) is True
    assert pkg._should_skip(exe, dist) is False


def test_package_release_strips_secrets(tmp_path: Path, monkeypatch: object) -> None:
    """PURPOSE: Zip is YTPM/… and never contains token.json or builder secrets."""
    dist = tmp_path / "dist" / "YTPM"
    dist.mkdir(parents=True)
    (dist / "YTPM.exe").write_bytes(b"MZ")
    (dist / "_internal").mkdir()
    (dist / "_internal" / "payload.bin").write_bytes(b"ok")
    (dist / "token.json").write_text("secret", encoding="utf-8")
    (dist / "quota_ledger.json").write_text("{}", encoding="utf-8")
    (dist / ".env").write_text("YOUTUBE_CLIENT_SECRET=real\n", encoding="utf-8")
    (dist / "list_mode").mkdir()
    (dist / "list_mode" / "snap.txt").write_text("nope", encoding="utf-8")

    monkeypatch.setattr(pkg, "DIST_DIR", dist)
    monkeypatch.setattr(pkg, "RELEASE_DIR", tmp_path / "release")
    monkeypatch.setattr(pkg, "ENV_EXAMPLE", Path(__file__).resolve().parents[1] / ".env.example")
    monkeypatch.setattr(pkg, "SHIP_README", Path(__file__).resolve().parents[1] / "packaging" / "README_SHIP.txt")
    monkeypatch.setattr(pkg, "HELP_PDF", tmp_path / "missing.pdf")

    zip_path = pkg.package_release(with_env=False)
    assert zip_path.is_file()
    names = zipfile.ZipFile(zip_path).namelist()
    assert "YTPM/YTPM.exe" in names
    assert "YTPM/_internal/payload.bin" in names
    assert "YTPM/README.txt" in names
    assert "YTPM/.env" in names
    assert "YTPM/.env.example" in names
    assert "YTPM/token.json" not in names
    assert not any("list_mode" in n for n in names)
    env_text = zipfile.ZipFile(zip_path).read("YTPM/.env").decode("utf-8")
    assert "YOUTUBE_CLIENT_SECRET=real" not in env_text
    assert "YOUTUBE_CLIENT_ID=" in env_text
