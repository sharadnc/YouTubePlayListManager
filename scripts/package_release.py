"""
PURPOSE:
    Zip dist\\YTPM into a distributable Windows release (no Python required
    on the user PC).

INTERNAL LOGIC:
    1. Require dist/YTPM/YTPM.exe.
    2. Copy runtime files into a staging folder, excluding secrets and logs.
    3. Always ship .env.example. Default .env is a clean template (empty
       Client ID/Secret) unless --with-env copies the builder's .env.
    4. Add packaging/README_SHIP.txt as README.txt and optional Help PDF.
    5. Write release/YTPM-<version>-windows.zip.

EXAMPLE INVOCATION:
    python scripts/package_release.py
    python scripts/package_release.py --with-env
    # Expected: release/YTPM-1.0.0-windows.zip
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Optional, Set

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist" / "YTPM"
RELEASE_DIR = ROOT / "release"
STAGE_NAME = "_stage_ytpm"
SHIP_README = ROOT / "packaging" / "README_SHIP.txt"
ENV_EXAMPLE = ROOT / ".env.example"
HELP_PDF = ROOT / "docs" / "YTPM_Tutorials_Help.pdf"

SKIP_NAMES: Set[str] = {
    "token.json",
    "quota_ledger.json",
    "sort_queue.json",
    "gui_settings.json",
    "gui_crash.log",
    "gui_out.log",
    "gui_err.log",
    ".env",
}
SKIP_SUFFIXES = {".log", ".pyc"}
SKIP_DIR_NAMES: Set[str] = {"list_mode", "exports", "__pycache__"}


def _app_version() -> str:
    """
    PURPOSE:
        Read YTPM version without importing the full package (avoids SSL/GUI).

    INTERNAL LOGIC:
        Parses __version__ from ytpm/__init__.py.

    EXAMPLE INVOCATION:
        _app_version()  # "1.0.0"
    """
    text = (ROOT / "ytpm" / "__init__.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return "0.0.0"


def _should_skip(path: Path, dist_root: Path) -> bool:
    """
    PURPOSE:
        Decide whether a dist file belongs in the user zip.

    INTERNAL LOGIC:
        Drops secrets, logs, and runtime data folders.

    EXAMPLE INVOCATION:
        _should_skip(dist_root / "token.json", dist_root)
    """
    rel = path.relative_to(dist_root)
    if path.name in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIXES:
        return True
    if any(part in SKIP_DIR_NAMES for part in rel.parts):
        return True
    return False


def _iter_files(dist_root: Path) -> Iterable[Path]:
    """
    PURPOSE:
        Walk dist/YTPM for zip members.

    INTERNAL LOGIC:
        Files only; skip rules applied by caller.

    EXAMPLE INVOCATION:
        list(_iter_files(DIST_DIR))
    """
    yield from (p for p in dist_root.rglob("*") if p.is_file())


def stage_payload(*, with_env: bool) -> Path:
    """
    PURPOSE:
        Build a clean folder that will become the zip root (YTPM/).

    INTERNAL LOGIC:
        Copies allowed files; writes README.txt, .env.example, and .env.

    EXAMPLE INVOCATION:
        stage_payload(with_env=False)
    """
    if not (DIST_DIR / "YTPM.exe").is_file():
        raise FileNotFoundError(
            f"Missing {DIST_DIR / 'YTPM.exe'}. Run Build_YTPM.bat first."
        )
    stage = RELEASE_DIR / STAGE_NAME
    if stage.exists():
        shutil.rmtree(stage)
    dest_root = stage / "YTPM"
    dest_root.mkdir(parents=True)

    for src in _iter_files(DIST_DIR):
        if _should_skip(src, DIST_DIR):
            continue
        rel = src.relative_to(DIST_DIR)
        target = dest_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)

    if SHIP_README.is_file():
        shutil.copy2(SHIP_README, dest_root / "README.txt")
    if ENV_EXAMPLE.is_file():
        shutil.copy2(ENV_EXAMPLE, dest_root / ".env.example")
        env_src = ROOT / ".env" if with_env and (ROOT / ".env").is_file() else ENV_EXAMPLE
        shutil.copy2(env_src, dest_root / ".env")
    if HELP_PDF.is_file():
        shutil.copy2(HELP_PDF, dest_root / "YTPM_Tutorials_Help.pdf")
    return dest_root


def write_zip(payload_root: Path, zip_path: Path) -> Path:
    """
    PURPOSE:
        Compress the staged YTPM folder into a zip.

    INTERNAL LOGIC:
        Members are YTPM/... so unzip creates one folder.

    EXAMPLE INVOCATION:
        write_zip(stage / "YTPM", Path("release/YTPM-1.0.0-windows.zip"))
    """
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.is_file():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in payload_root.rglob("*"):
            if file_path.is_file():
                arc = Path("YTPM") / file_path.relative_to(payload_root)
                zf.write(file_path, arcname=str(arc).replace("\\", "/"))
    return zip_path


def package_release(*, with_env: bool = False) -> Path:
    """
    PURPOSE:
        Produce release/YTPM-<version>-windows.zip for distribution.

    INTERNAL LOGIC:
        stage_payload then write_zip; deletes the stage folder afterward.

    EXAMPLE INVOCATION:
        package_release()
    """
    version = _app_version()
    zip_path = RELEASE_DIR / f"YTPM-{version}-windows.zip"
    payload = stage_payload(with_env=with_env)
    try:
        write_zip(payload, zip_path)
    finally:
        stage = RELEASE_DIR / STAGE_NAME
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
    return zip_path


def main(argv: Optional[list[str]] = None) -> int:
    """
    PURPOSE:
        CLI for building the Windows zip.

    INTERNAL LOGIC:
        --with-env includes the builder's .env (shared OAuth client). Default
        ships empty Client ID/Secret from .env.example.

    EXAMPLE INVOCATION:
        python scripts/package_release.py
    """
    parser = argparse.ArgumentParser(
        description="Zip dist/YTPM for multi-user distribution"
    )
    parser.add_argument(
        "--with-env",
        action="store_true",
        help="Include this machine's .env (Client ID/Secret). Use only for a "
        "shared org OAuth client; never publish that zip publicly.",
    )
    args = parser.parse_args(argv)
    try:
        out = package_release(with_env=bool(args.with_env))
    except Exception as exc:
        print(f"package_release failed: {exc}", file=sys.stderr)
        return 1
    size = out.stat().st_size
    print(f"Wrote {out} ({size:,} bytes)")
    if args.with_env:
        print("WARNING: zip contains .env secrets. Distribute only inside your org.")
    else:
        print("Users must fill YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET in .env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
